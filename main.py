import asyncio
import json
import logging
import httpx  # Import httpx for making HTTP requests
from fastapi import (Depends, FastAPI, HTTPException, WebSocket,
                    WebSocketDisconnect, status)
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# Other imports...
from chatcode.api_call import *
from chatcode.function import *
from chatcode.groq_function import *
from chatcode.onbapi_call import *
from chatcode.onbfunction import (collect_user_input, get_jsonfile,
                                validate_input)

app = FastAPI()

# CORS middleware setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files from the "frontend_project" directory

# URL to fetch the HTML from
FRONTEND_URL = "https://employee-chat-fe-dev-43e1f5279cb7.herokuapp.com"  # Replace with your actual URL

@app.get("/")
async def serve_frontend():
    async with httpx.AsyncClient() as client:
        response = await client.get(FRONTEND_URL)
        if response.status_code != 200:
            raise HTTPException(status_code=404, detail="Frontend not found")
        
        # Modify the response content to ensure that CSS and JS point to the correct URLs
        html_content = response.text
        # This assumes your CSS and JS are served from the same Heroku URL
        html_content = html_content.replace('href="/static/', f'href="{FRONTEND_URL}/static/')
        html_content = html_content.replace('src="/static/', f'src="{FRONTEND_URL}/static/')
        
        return HTMLResponse(content=html_content)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.websocket("/ws/onboard")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    try:
        while True:
            data = await websocket.receive_text()
            data_json = json.loads(data)
            user_message = data_json.get("message", "").strip().lower()            

            if user_message == 'quit':
                await websocket.send_text("Please wait,You will be Navigated to Login Screen")  # Redirect to the new page
                await asyncio.sleep(3)  # Add a 3-second delay
                await websocket.send_text("navigate")  # Redirect to the new page
                break

            elif user_message == 'onboard':
                file = get_jsonfile()
                details = await collect_user_input(websocket, file, validate_input)
                response = await onboard_personal_details(websocket,details)
                if response != "Email Send Successfully":
                    await websocket.send_text(response)
                    await websocket.send_text("You will be Navigated to Login Screen")  # Redirect to the new page
                    await asyncio.sleep(3)  # Add a 3-second delay
                    await websocket.send_text("navigate")
                    break
                else:
                    await websocket.send_text("Your details have been saved successfully. Check your personal mail for Username and Password.")
                    await websocket.send_text("You will be Navigated to Login Screen")  # Redirect to the new page
                    await asyncio.sleep(2)  # Add a 3-second delay
                    await websocket.send_text("navigate")
                    break
            else:
                await websocket.send_text("Please enter 'Onboard' in the chat below or 'Quit' to exit.")
    
    except WebSocketDisconnect:
        logger.info("Client disconnected")
    except Exception as e:
        logger.error(f"Exception: {e}")
        await websocket.send_text(json.dumps({"Response": "An error occurred. Please try again."}))


@app.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            try:
                # Receiving data
                data = await websocket.receive_text()
                data_json = json.loads(data)

                token = data_json.get("token")
                user_message = data_json.get("message")
                role = data_json.get("role")
                apikey = data_json.get('apikey')
                model = data_json.get('model')
                
                

                # Check for 'quit' message
                if user_message.lower() == 'quit':
                    await websocket.send_text("Goodbye, Thanks for using our app!")
                    await asyncio.sleep(2)
                    await websocket.send_text("quit")
                    break
                
                # Main logic
                jsonfile = choose_json(role)
                projectinfo = load_project_info(jsonfile)
                response = await get_project_details(websocket, user_message, projectinfo,apikey,model)
                if response is None:
                    await asyncio.sleep(4)
                    continue
                query = response[0]
                project_name = response[1]
                try:
                    if int(query) >= 500 and project_name is None:
                        await asyncio.sleep(4)
                        await websocket.send_text('navigateerror')
                        break
                except ValueError:
                    print("Query is not a number, skipping numeric check. Proceeding to the next step.")
                project_details = get_project_script(project_name, jsonfile)
                payload_details = split_payload_fields(project_details)
                if payload_details != {}:
                    filled_cleaned = await fill_payload_values(websocket, query, payload_details,jsonfile, apikey, model)
                    # Check if response indicates a Groq API error
                    if isinstance(filled_cleaned, dict):
                        print('filled_cleaned is a dictionary, proceeding with dictionary processing')
                    elif filled_cleaned is None:
                        await asyncio.sleep(4)
                        continue
                    else:
                        try:
                            if int(filled_cleaned) >= 500 :
                                await asyncio.sleep(4)
                                await websocket.send_text('navigateerror')
                                break
                        except ValueError:
                            print("filled_cleaned is not a number, skipping numeric check. Proceeding to the next step.")
                else:
                    filled_cleaned = payload_details
                        
                
                validate_payload = validate(project_details, filled_cleaned) 
                
                # Handling PUT requests
                if validate_payload['method'] == 'PUT':
                    answer = await update_process(websocket, project_details, validate_payload)
                    logger.info(f"Answer from update_process: {answer}")
                else:
                    # Handling other requests
                    answer = await ask_user(websocket, project_details, validate_payload)
                    logger.info(f"Answer from ask_user: {answer}")
                
                answer['bearer_token'] = token

                    
                
                # Database operation
                result,payload = await database_operation(websocket, answer)
                
                if result == "Table" and payload == "Return":
                    await websocket.send_text("Glad to help! If you need more assistance, I'm just a message away.")
                    continue
                
                elif result and payload:
                    if result == 'Internal Server Error':
                        await websocket.send_text(f"{result}. Sorry for inconvenience, try after sometime.")
                        continue
                    else:
                        model_output = await nlp_response(websocket, result, payload,apikey, model)
                        
                        if model_output is None:
                            await asyncio.sleep(4)
                            continue
                        try:
                            if int(model_output) >= 500:
                                await asyncio.sleep(4)
                                await websocket.send_text('navigateerror')
                                break
                            else:
                                await websocket.send_text(f"{model_output}. Glad to help! If you need more assistance, I'm just a message away.")
                                continue
                        except ValueError:
                            await websocket.send_text(f"{model_output}. Glad to help! If you need more assistance, I'm just a message away.")
                            continue
                elif result and  not payload:
                    
                    if isinstance(result, str):
                        result = json.loads(result)
                        result =  result['detail']
                        await websocket.send_text(f"{result}. Glad to help! If you need more assistance, I'm just a message away.")
                        continue
                    if 'detail' in result:
                        result =  result['detail']
                        await websocket.send_text(f"{result}. Glad to help! If you need more assistance, I'm just a message away.")
                        continue
                    else:
                        await websocket.send_text(f"check not payload")
                        continue
                
                else:
                    await websocket.send_text("Back end server error try again.")
                    await asyncio.sleep(3)
                    continue
                                                                    
            except Exception as e:
                await websocket.send_text(f"An error occurred: {str(e)}")


    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
        await asyncio.sleep(3)
    except Exception as e:
        logger.error(f"Unexpected error in WebSocket connection: {str(e)}")
        await asyncio.sleep(3)
    finally:
        await websocket.close()
