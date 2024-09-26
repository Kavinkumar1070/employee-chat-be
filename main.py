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
app.mount("/templates", StaticFiles(directory="../Frontend/templates"), name="templates")

# URL to fetch the HTML from
FRONTEND_URL = "http://127.0.0.1:5500/templates/index.html"  # Replace with your actual URL

@app.get("/")
async def get():
    async with httpx.AsyncClient() as client:
        response = await client.get(FRONTEND_URL)
        if response.status_code != 200:
            return HTMLResponse("File not found", status_code=404)
        return HTMLResponse(response.text)


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
            print(f"Received message: '{user_message}'")  # Debugging: Log the received message

            if user_message == 'quit':
                await websocket.send_text("Please wait,You will be Navigated to Login Screen")  # Redirect to the new page
                await asyncio.sleep(3)  # Add a 3-second delay
                await websocket.send_text("navigate")  # Redirect to the new page
                break

            elif user_message == 'onboard':
                file = get_jsonfile()
                details = await collect_user_input(websocket, file, validate_input)
                details['dateofbirth'] = datetime.strptime(details['dateofbirth'], '%Y-%m-%d').strftime('%Y-%m-%d')
                details['contactnumber'] = int(details['contactnumber'])
                print('*****************************')
                print(details)
                print('*****************************')
                response = await onboard_personal_details(websocket,details)
                print(response)
                if response != "Email Send Successfully":
                    await websocket.send_text(response)
                    await websocket.send_text("You will be Navigated to Login Screen")  # Redirect to the new page
                    await asyncio.sleep(3)  # Add a 3-second delay
                    await websocket.send_text("navigate")
                    break
                else:
                    await websocket.send_text("Your details have been saved successfully. Check your personal mail for Username and Password.")
                    await websocket.send_text("You will be Navigated to Login Screen")  # Redirect to the new page
                    await asyncio.sleep(3)  # Add a 3-second delay
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
                print('________________________________________________________________________________________')
                print("data json :", data_json)
                print('________________________________________________________________________________________')

                token = data_json.get("token")
                user_message = data_json.get("message")
                role = data_json.get("role")
                apikey = data_json.get('apikey')
                model = data_json.get('model')

                # Check for 'quit' message
                if user_message.lower() == 'quit':
                    await websocket.send_text("Goodbye, Thanks for using our app!")
                    await asyncio.sleep(3)
                    await websocket.send_text("quit")
                    break
                
                # Main logic
                jsonfile = choose_json(role)
                response = await get_project_details(websocket, user_message, jsonfile, apikey, model)
                query = response[0]
                project_name = response[1]
                print('________________________________________________________________________________________')
                print('Query amd Project name') 
                print(query)
                print(project_name)
                if isinstance(project_name, str) and project_name == "Groq API error":
                        await websocket.send_text("Error: Failed to process the response from Groq API.")
                        await asyncio.sleep(3)
                        await websocket.send_text('navigateerror')
                        continue
                print('________________________________________________________________________________________')
                project_details = get_project_script(project_name, jsonfile)
                print('________________________________________________________________________________________')
                print('Project Details') 
                print(project_details)
                print('________________________________________________________________________________________')
                payload_details = split_payload_fields(project_details)
                print('________________________________________________________________________________________')
                print('Payload Details') 
                print(payload_details)
                print('________________________________________________________________________________________')
                if payload_details != {}:
                    print('________________________________________________________________________________________')
                    print('Payload Detail is Not Empty')
                    print("123",model)
                    filled_cleaned = await fill_payload_values(websocket, query, payload_details,jsonfile, apikey, model)
                    # Check if response indicates a Groq API error
                    if isinstance(filled_cleaned, str) and filled_cleaned == "Groq API error":
                        await websocket.send_text("Error: Failed to process the response from Groq API.")
                        await asyncio.sleep(3)
                        await websocket.send_text('navigateerror')
                        continue
                else:
                    print('________________________________________________________________________________________')
                    print('Payload Detail is Empty')
                    filled_cleaned = payload_details
                        
                
                validate_payload = validate(project_details, filled_cleaned) 
                print('Validate Payload') 
                print(validate_payload)
                print('________________________________________________________________________________________')
                
                # Handling PUT requests
                if validate_payload['method'] == 'PUT':
                    answer = await update_process(websocket, project_details, validate_payload)
                    print("---------------------------------------------------------------------------------------------------------------------------")
                    logger.info(f"Answer from update_process: {answer}")
                    print("---------------------------------------------------------------------------------------------------------------------------")
                else:
                    # Handling other requests
                    answer = await ask_user(websocket, project_details, validate_payload)
                    print("---------------------------------------------------------------------------------------------------------------------------")
                    logger.info(f"Answer from ask_user: {answer}")
                    print("---------------------------------------------------------------------------------------------------------------------------")
                
                answer['bearer_token'] = token

                    
                
                # Database operation
                result,payload = await database_operation(websocket, answer)
                
                print('result :',result)
                print('payload :',payload)
                
                if result == "Table" and payload == "Return":
                    await websocket.send_text("Glad to help! If you need more assistance, I'm just a message away.")
                    continue
                
                elif result and payload:
                    if result == 'Internal Server Error':
                        await websocket.send_text(f"{result}. Sorry for inconvenience, try after sometime.")
                        continue
                    else:
                        model_output = await nlp_response(websocket, result, payload, apikey, model)
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
                print('Chat error')
                await websocket.send_text(f"An error occurred: {str(e)}")


    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
        await asyncio.sleep(3)
    except Exception as e:
        print('out of chat')
        logger.error(f"Unexpected error in WebSocket connection: {str(e)}")
        await asyncio.sleep(3)
    finally:
        await websocket.close()


