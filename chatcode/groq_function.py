import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict

import groq
from dotenv import load_dotenv
from fastapi import WebSocket
from groq import Groq

from chatcode.function import *

# Setup logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

load_dotenv()

async def get_project_details(websocket: WebSocket, query: str, projectinfo: dict,apikey,model):
    client = Groq(api_key=os.getenv(apikey))
    try:
        response = client.chat.completions.create(
            model=os.getenv(model),
            messages=[
                {
                    "role": "system",
                    "content": f"""
                        You are an AI assistant trained to extract project names based on project descriptions. Follow these steps:
                        
                        1. Correct any grammatical or spelling errors in the query.
                        2. Identify and extract keywords and context from the user query: "{query}" to capture the intent.
                        3. Review the provided project descriptions: {projectinfo}.
                        4. Analyze the intent and match it with the project names based on the descriptions.
                        5. If a project name matches the query context, return that project name.
                        6. If no project name matches or the query is unclear, return 'None'.
                        7. Return the result in a JSON object with the format shown below.
                        
                        Example:
                        Query: "How do I update my project?"
                        Project Titles and Descriptions: {projectinfo}
                        Response:
                        ~~~
                        {{
                            "project": "Project XYZ"
                        }}
                        ~~~
                    Ensure the response is enclosed with `~~~` before and after the JSON output. Do not include any additional explanations.
            """
                },
                {
                    "role": "user",
                    "content": f"Extract the project name from the following query: {query} and Project Titles and Descriptions: {projectinfo}."
                }
            ]
        )

        response_text = response.choices[0].message.content.strip()
        json_start_idx = response_text.find("~~~")
        json_end_idx = response_text.rfind("~~~") + 1
        result = response_text[json_start_idx:json_end_idx]
        result = sanitize_json_string(result)
        project_name = json.loads(result).get("project")
        project_name = project_available_check(project_name, projectinfo)

        if project_name == "None" or project_name is None:
            await websocket.send_text("You have asked for an irrelevant query. Ask anything from the listed projects:")
            user_input = await websocket.receive_text()
            user_input_data = json.loads(user_input)
            query = user_input_data.get("message")
            return await get_project_details(websocket, query, projectinfo, apikey, model)
        return query, project_name
    
    except Exception as e:
        error_str = str(e)
        print(error_str)
        if "Error code:" in error_str:
            status_code = error_str.split("Error code:")[1].split(" - ")[0].strip()
            try:
                error_message = e.response.json() if hasattr(e, 'response') else {}
                error_msg = error_message.get('error', {}).get('message', 'Unknown error message')
                # error_code = error_message.get('error', {}).get('code', 'Unknown code')
                # print(f"Status Code: {status_code}")
                # print(f"Error Code: {error_code}")
                # print(f"Error Message: {error_msg}")
    
                # Classify errors based on status code
                if status_code in ['400','404', '422', '429']:
                    await websocket.send_text(f"Error code:{status_code} and Error Message:{error_msg}")
                    await websocket.send_text("Client Error,too many request try with different api or model")
                elif int(status_code) ==  401:
                    await websocket.send_text(f"Error code:{status_code} and Error Message:{error_msg}")
                    await websocket.send_text("use another api key or contact admin")
                elif int(status_code) >= 500:
                    await websocket.send_text("Server Error, try again after sometime")
                    return status_code , None
            except Exception as inner_e:
                await websocket.send_text(f"Failed to parse error response: {inner_e}")
                await websocket.send_text("contact admin")
        else:
            await websocket.send_text("An unknown error occurred :",e)
            await websocket.send_text("contact admin")
        


async def fill_payload_values(websocket: WebSocket, query: str, payload_details: dict, jsonfile, apikey, model) -> Dict[str, Any]:
    client = Groq(api_key=os.getenv(apikey))
    try:
        response = client.chat.completions.create(
            model=os.getenv(model),
            messages=[
                {
                    "role": "system",
                    "content": f"""You are an expert in filling payload values from a user query based on a configuration file.

                        Strict Instructions:
                        1. **Capture Only from User Query:** Extract values strictly from the user query: {query}. Do **not** infer or assume any values.                        
                        2. **Use Assigned Values:** If a value is missing in the user query or doesn't match the required format/choices, **use the assigned value** specified in the configuration file {payload_details}.        
                        3. **Fill Missing Fields with Assigned Values:** For each field not found in the user query, refer to the configuration file for the field's assigned value. If no valid input is found in the query and no assigned value is provided, use "None".
                        4. **JSON Response Format:** Return only the payload JSON response in the following format, enclosed with `~~~` before and after the response.
                    
                    Example output format:
                        query: get leave records by month and year
                        ~~~{{
                            "payload": {{
                                "employee_id": "None",
                                "monthnumber": "None",
                                "yearnumber": "None"
                            }}
                        }}~~~
                """
                },
                {
                    "role": "user",
                    "content": f"Analyze the following query: {query} with config file: {payload_details} and extract values based on the user input or use assigned values from the config file."
                }
            ]
        )

        response_text = response.choices[0].message.content.strip()
        json_start_idx = response_text.find("~~~")
        json_end_idx = response_text.rfind("~~~") + 1
        result = response_text[json_start_idx:json_end_idx]
        sanitized_response = sanitize_json_string(result)
        try:
            result = json.loads(sanitized_response)
            response_config = result.get('payload', {})
            verified_payload = verify_values_from_query(
                query, response_config, payload_details)
            return verified_payload

        except json.JSONDecodeError:
            logger.error("Error: Failed to decode JSON from the response on fill_payload_values.")
            await websocket.send_text("Error: Failed to decode JSON from the response on fill_payload_values.")


    except Exception as e:
        error_str = str(e)
        if "Error code:" in error_str:
            status_code = error_str.split("Error code:")[1].split(" - ")[0].strip()
            try:
                error_message = e.response.json() if hasattr(e, 'response') else {}
                error_msg = error_message.get('error', {}).get('message', 'Unknown error message')
                if status_code in ['400','404', '422', '429']:
                    await websocket.send_text(f"Error code:{status_code} and Error Message:{error_msg}")
                    await websocket.send_text("Client Error,too many request try with different api or model")
                elif int(status_code) ==  401:
                    await websocket.send_text(f"Error code:{status_code} and Error Message:{error_msg}")
                    await websocket.send_text("use another api key or contact admin")
                    return status_code
                elif int(status_code) >= 500:
                    await websocket.send_text("Server Error, try again after sometime")
                    return status_code
            except Exception as inner_e:
                await websocket.send_text(f"Failed to parse error response: {inner_e}")
                await websocket.send_text("contact admin")
        else:
            await websocket.send_text("An unknown error occurred :",e)
            await websocket.send_text("contact admin")


async def nlp_response(websocket: WebSocket, answer, payload, apikey, model):
    try:
        client = Groq(api_key=os.getenv(apikey))
        response = client.chat.completions.create(
            model=os.getenv(model),
            messages=[
                {
                    "role": "system",
                    "content": """
                    You are an AI assistant responsible for explaining technical SQL operation results in simple and user-friendly terms. 
                    The user has performed a CRUD operation (Create, Read, Update, Delete) using an API that interacts with a database.
                    
                    Provide a concise, clear summary of the operation result in **under 40 words**. Include the relevant payload values.
                    Avoid technical jargon and ensure the explanation is easily understandable by non-technical users.
                    """
                },
                {
                    "role": "user",
                    "content": f"The API response is: {answer}. The payload is: {payload}. Please summarize the result in a user-friendly way."
                }
            ]
        )
        response_text = response.choices[0].message.content.strip()
        
        return response_text


    except Exception as e:
        error_str = str(e)
        if "Error code:" in error_str:
            status_code = error_str.split("Error code:")[1].split(" - ")[0].strip()
            try:
                error_message = e.response.json() if hasattr(e, 'response') else {}
                error_msg = error_message.get('error', {}).get('message', 'Unknown error message')
                if status_code in ['400','404', '422', '429']:
                    await websocket.send_text(f"Error code:{status_code} and Error Message:{error_msg}")
                    await websocket.send_text("Client Error,too many request try with different api or model")
                elif int(status_code) ==  401:
                    await websocket.send_text(f"Error code:{status_code} and Error Message:{error_msg}")
                    await websocket.send_text("use another api key or contact admin")
                elif int(status_code) >= 500:
                    await websocket.send_text("Server Error, try again after sometime")
                    return status_code
            except Exception as inner_e:
                await websocket.send_text(f"Failed to parse error response: {inner_e}")
                await websocket.send_text("contact admin")
        else:
            await websocket.send_text("An unknown error occurred :",e)
            await websocket.send_text("contact admin")
