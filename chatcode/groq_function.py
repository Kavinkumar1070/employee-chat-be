import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict
from datetime import date

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
                
        1. **Correct any grammatical or spelling errors in the query:** If the query contains any spelling or grammatical mistakes, fix them to ensure clarity.
        2. **Analyze the intent of the user query:** Focus on understanding the intent behind the query based on the key actions or objectives mentioned. The goal is to capture the core purpose of the query, not just its keywords. Query: "{query}".
        3. **Review the provided project titles and descriptions:** Consider the list of project titles {projectinfo.keys()} and the descriptions {projectinfo.values()}. Match the query based primarily on the **intent** captured in Step 2, ensuring the description of the project aligns with the user's needs.
        4. **Use keywords for verification only:** After matching the intent with the project descriptions, check the keywords from the query against the titles/descriptions to verify that the selected project makes sense contextually. Keywords are only used for verification, not as the main factor for project selection.
        5. **Handle ambiguous or short queries:**
            - If the query consists of a single word (like "get", "update", etc.), treat it as too vague and return `"None"`.
            - If multiple projects could match the query's intent (i.e., the query is unclear or ambiguous), return `"None"`. This ensures clarity in matching.
        6. **Return the matching project name if one is found:** If the project that best aligns with the query’s intent is clear, return that project name.
        7. **Handle unclear or no matches:** If no project name matches the query, or if the query is unclear, return `"None"`.
        8. **Return the result in a JSON object:** Format the result as follows, ensuring it is enclosed in `~~~`.
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
        today_date = date.today().strftime("%d-%m-%Y")
        response = client.chat.completions.create(
            model=os.getenv(model),
            messages=[
            {
                "role": "system",
                "content": f"""You are an expert in filling payload values from a user query based on a configuration file.

                Strict Instructions:
                1. **Capture Only from User Query:** Extract values strictly from the user query: {query}. Do **not** infer or assume any values.
                2. **Date Parsing:** Convert natural language expressions for dates such as 'today', 'tomorrow', 'next Friday', 'October 23rd', etc., into the standard format 'DD-MM-YYYY'. Use the current date {today_date} as a reference for relative dates like 'today', 'tomorrow', or 'next Friday'. Always assume the current year unless another year is explicitly mentioned.
                3. **Use Assigned Values:** If a value is missing in the user query or doesn't match the required format/choices, **use the assigned value** specified in the configuration file {payload_details}.
                4. **Fill Missing Fields with Assigned Values:** For each field not found in the user query, refer to the configuration file for the field's assigned value. If no valid input is found in the query and no assigned value is provided, use "None".
                5. **JSON Response Format:** Return only the payload JSON response in the following format, enclosed with `~~~` before and after the response.

                Example output format:
                    query: I would like to apply for leave starting from next Friday for personal work
                    ~~~{{
                        "payload": {{
                            "leave_type": "personal",
                            "duration": "None",
                            "start_date": "DD-MM-YYYY",  # assuming today is {today_date}
                            "total_days": "None",
                            "reason": "personal work"
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
            return response_config

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

                Provide a concise, clear summary of the operation result in **under 50 words**. 
                Start by explaining if the operation was successful or failed. Then explain the relevant payload values. 
                Avoid technical jargon and ensure the explanation is easily understandable by non-technical users.
                """
            },
            {
                "role": "user",
                "content": f"The API response is: {answer}. The payload is: {payload}. Please summarize the result in a user-friendly way, first explaining the result (success/failure) and then the payload."
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
