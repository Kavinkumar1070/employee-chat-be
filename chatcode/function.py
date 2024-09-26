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

# Setup logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

load_dotenv()

# choose suitable json script


def choose_json(role):
    json_file = ['admin', 'employee', 'teamlead', 'onboard']
    for i in json_file:
        if i == role:
            return i + '.json'

# clean the model converted json output


def sanitize_json_string(response_text: str) -> str:
    response_text = response_text.strip()
    json_match = re.search(
        r'\{(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*\}', response_text, re.DOTALL)
    if json_match:
        json_string = json_match.group(0)
        json_string = re.sub(r'\\_', '_', json_string)
        try:
            parsed_json = json.loads(json_string)
            return json.dumps(parsed_json, indent=4)
        except json.JSONDecodeError:
            return "{}"
    return "{}"


async def get_project_details(websocket: WebSocket, query: str, jsonfile: str, apikey, model):
    projectinfo = {}
    try:
        with open(jsonfile, 'r') as f:
            json_config = json.load(f)
            project_names = json_config.keys()
            for i in project_names:
                if 'project description' in json_config[i]:
                    projectinfo[i] = json_config[i]['project description']
                else:
                    logging.warning(
                        f"Warning: 'project description' missing for {i}")
    except Exception as e:
        print(f"Error while processing the get project details: {e}")
        await websocket.send_text("Error while processing the get project details : project info")

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
            2. Review the provided project descriptions: {projectinfo}.
            3. Analyze the user query: "{query}" to determine which project name, if any, is referenced based on the descriptions.
            4. If a project name matches the query context, return that project name.
            5. If no project name matches or the query is unclear, return 'None'.
            6. The result should be a JSON object with the format shown below.

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

        if project_name == "None" or project_name is None:
            await websocket.send_text("You have asked for an irrelevant query. Ask anything from the listed projects:")
            user_input = await websocket.receive_text()
            user_input_data = json.loads(user_input)
            query = user_input_data.get("message")
            return await get_project_details(websocket, query, jsonfile, apikey, model)
        return query, project_name

    except client.exceptions.GroqAPIError as groq_error:
        print(f"Groq API error: {groq_error}")
        await websocket.send_text("Error: Failed to process the response from Groq API.")
        return "query", "Groq API error"

    except Exception as e:
        print(f"Error while processing the response: {e}")
        await websocket.send_text(e)
        await websocket.send_text("Error: Failed to process the response on get project detail.")


def get_project_script(project_name: str, jsonfile: str):
    try:
        with open(jsonfile, 'r') as f:
            json_config = json.load(f)
            project_script = json_config.get(project_name)
            return project_script

    except FileNotFoundError:
        print("Error: The file was not found.")
        return "Error: The configuration file was not found on get_project_script."
    except json.JSONDecodeError:
        print("Error: Failed to decode JSON from the file.")
        return "Error: Failed to read the configuration file on get_project_script."


def split_payload_fields(project_detail: dict):
    try:
        payload_detail = project_detail['payload']
        return payload_detail

    except KeyError as e:
        print(
            f"Error: Missing expected key in project details on split_payload_fields: {e}")
        return "Error: Missing expected key in project details on split_payload_fields."
    except TypeError:
        print("Error: The project detail provided is not a dictionary on split_payload_fields.")
        return "Error: The project detail provided is not a dictionary on split_payload_fields."


def verify_values_from_query(query, payload, config):
    query_tokens = re.findall(r'\b\w+\b', query.lower())
    verified_payload = {}
    for field, value in payload.items():
        if isinstance(value, str) and value.lower() in query_tokens:
            verified_payload[field] = value
        elif value == config.get(field, "None"):
            verified_payload[field] = value
        else:
            verified_payload[field] = "None"
    return verified_payload


async def fill_payload_values(websocket: WebSocket, query: str, payload_details: dict, jsonfile: str, apikey, model) -> Dict[str, Any]:
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
            logger.error(
                "Error: Failed to decode JSON from the response on fill_payload_values.")
            await websocket.send_text("Error: Failed to decode JSON from the response on fill_payload_values.")

    except client.exceptions.GroqAPIError as groq_error:
        print(f"Groq API error: {groq_error}")
        await websocket.send_text("Error: Failed to process the response from Groq API.")
        return "Groq API error"

    except Exception as e:
        logger.error(
            f"Error while processing the response on fill_payload_values: {e}")
        await websocket.send_text(e)
        await websocket.send_text("Error while processing the response on fill_payload_values")


def validate(payload_detail, response_config):
    payload_details = payload_detail['payload']
    validated_payload = {}

    for key, values in payload_details.items():
        if key in response_config.keys():
            value = response_config.get(key)
            # required = values.get('required', False)

            # Normalize 'None' string to None
            if value == "None":
                value = None

            # If the field is required and missing, set to None
            if value is None:
                # if required:
                validated_payload[key] = None
                continue

            # Check datatype and format
            datatype = values['datatype']

            if datatype == 'regex':
                pattern = values['format']
                if not re.match(pattern, value):
                    validated_payload[key] = None
                    continue

            elif datatype == 'date':
                formats = values.get('formats', [])
                if not formats:
                    formats = [
                        '%Y-%m-%d',       # 2024-09-13
                        '%Y/%m/%d',       # 2024/09/13
                        '%Y.%m.%d',       # 2024.09.13
                        '%Y %b %d',       # 2024 Sep 13]
                    ]
                value = value.strip()
                valid_date = False
                for fmt in formats:
                    try:
                        datetime.strptime(value, fmt)
                        valid_date = True
                        break
                    except ValueError:
                        continue

                if not valid_date:
                    validated_payload[key] = None
                    continue

            elif datatype == 'choices':
                choices = values['choices']
                if value not in choices:
                    validated_payload[key] = None
                    continue

            elif datatype == 'string' and value != 'None':
                if not isinstance(value, str):
                    validated_payload[key] = None
                    continue

            elif datatype == 'integer':
                try:
                    # Try to cast the value to an integer
                    int(value)
                except ValueError:
                    validated_payload[key] = None
                    continue

            elif datatype == 'mobile':
                try:
                    # Check if the value is an integer and has 10 digits
                    int_value = int(value)
                    if len(str(int_value)) != 10:
                        validated_payload[key] = None
                        continue
                except ValueError:
                    validated_payload[key] = None
                    continue

            # If all checks pass, keep the value
            validated_payload[key] = value

    final_response = {
        'project': payload_detail['project'],
        'url': payload_detail['url'],
        'method': payload_detail['method'],
        'payload': validated_payload
    }
    return final_response


async def update_process_with_user_input(websocket: WebSocket, project_details: dict, data: dict):
    try:
        update_payload = data['payload']
        available_fields = list(update_payload.keys())

        if len(available_fields) <= 2:
            print('less than 2')
            verified_fields = available_fields
        else:
            verified_fields = []
            for key, value in project_details['payload'].items():
                if value['required'] == True:
                    verified_fields.append(key)
            print('true fields:', verified_fields)

            available_field = []
            for key, value in project_details['payload'].items():
                if value['required'] == False:
                    available_field.append(key)
            print('false fields:', available_field)

            if len(available_field) != 0:

                choices_list = ",".join(available_field)
                print(choices_list)
                choices_list = choices_list + ",All"
                print(choices_list)
                message = 'Select "All" or pick a field from the available choices below'
                await websocket.send_text(f"{message}.Fields:{choices_list} ")
                fields_input = await websocket.receive_text()
                fields_input = json.loads(fields_input)
                fields_input = fields_input.get('message')

                if not fields_input:
                    await websocket.send_text("No fields provided. Please try again.")
                    return None

                if fields_input.lower() == 'all':
                    print('all')
                    print(available_fields)
                    verified_fields.extend(available_fields)
                else:
                    print('selected columns')
                    fields_to_update = [field.strip().replace("'", "").replace(
                        "[", "").replace("]", "") for field in fields_input.split(',')]
                    available_fields = [
                        field for field in fields_to_update if field and field in available_fields]
                    verified_fields.extend(available_fields)

            for key, value in project_details['payload'].items():
                if value['required'] == True and key not in verified_fields:
                    verified_fields.append(key)
            print("final output", verified_fields)

        if not verified_fields:
            await websocket.send_text("No Verified Fields check update_process_with_user_input.")

        updated_fields = {}
        for i in verified_fields:
            updated_fields[i] = 'None'

        updated = {'project': project_details['project'],
                   'url': project_details['url'],
                   'method': project_details['method'],
                   'payload': updated_fields}

        response = await ask_user(websocket, project_details, updated)
        return response

    except Exception as e:
        print(f"Error occurred in update_process_with_user_input: {e}")
        await websocket.send_text(f"Error occurred in update_process_with_user_input: {e}")


async def update_process(websocket: WebSocket, project_details: dict, data: dict):
    update_payload = data['payload']
    if all(value is None or value == "None" for value in update_payload.values()):
        updated_details = await update_process_with_user_input(websocket, project_details, data)
        print("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
        print("update output:", updated_details)
        print("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
        return updated_details
    else:
        b = data['payload']
        filtered_payload = {}

        # Filter out None and "None" values from the payload
        for key, value in b.items():
            if value is not None and value != "None":
                filtered_payload[key] = value

        # Create a new dictionary including project, url, method, and filtered payload
        result = {
            'project': data['project'],
            'url': data['url'],
            'method': data['method'],
            'payload': filtered_payload
        }
        print("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
        print("update output direct:", result)
        print("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
        return result


def normalize_string(value: str) -> str:
    if isinstance(value, str):
        return value.strip().lower()


async def ask_user(websocket: WebSocket, pro, pay):
    abc = pay['payload'].copy()
    for key, value in abc.items():
        if value is None or value == "None":
            des = pro['payload'][key]['description']
            data_type = pro['payload'][key]['datatype']

            if data_type == "choices":
                choices = pro['payload'][key]['choices']
                choices_list = ",".join(choices)
                await websocket.send_text(f"Please provide  {des}. Choices are: {choices_list}")
            else:
                await websocket.send_text(f"Please provide {des}")

            user_input = await websocket.receive_text()
            user_input_data = json.loads(user_input)
            cleanstr = user_input_data.get("message")
            abc[key] = normalize_string(cleanstr)
            valid = validate(pro, abc)

            if valid['payload'][key] is None:
                return await ask_user(websocket, pro, valid)
            else:
                pay['payload'][key] = abc[key]
    return pay


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

    except client.exceptions.GroqAPIError as groq_error:
        print(f"Groq API error: {groq_error}")
        await websocket.send_text("Error: Failed to process the response from Groq API.")
        return "Groq API error"

    except Exception as e:
        logging.error(f"Error during API call: {e}")
        await websocket.send_text(f"Error occurred in nlp_response: {e}")
