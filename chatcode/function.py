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

def load_project_info(jsonfile: str) -> dict:
    projectinfo = {}
    try:
        with open(jsonfile, 'r') as f:
            json_config = json.load(f)
            project_names = json_config.keys()

            for project in project_names:
                if 'project description' in json_config[project]:
                    projectinfo[project] = json_config[project]['project description']
                else:
                    logging.warning(f"Warning: 'project description' missing for {project}")
    
    except Exception as e:
        print(f"Error while processing the project details: {e}")    
    return projectinfo


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


def project_available_check(project_name, projectinfo):
    if project_name not in projectinfo.keys():
        return None
    else:
        return project_name


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
                        '%d-%m-%Y',       # 2024-09-13
                        '%d/%m/%Y',       # 2024/09/13           
                        '%d.%m.%Y',       # 2024.09.13
                        '%d %b %Y',
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
                choices_list =  "All ,"  + choices_list 
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
            elif data_type == "integer":
                await websocket.send_text(f"Please provide  {des}. datatype:{data_type} ")
            elif data_type == "mobile":
                await websocket.send_text(f"Please provide  {des}. datatype:{data_type} ")
            elif data_type == "date":
                await websocket.send_text(f"Please provide  {des}. datatype:{data_type} ")
            elif data_type == "regex":
                regex_format = pro['payload'][key]['format']
                await websocket.send_text(f"Please provide  {des}. datatype:{data_type},regexformat:{regex_format} ")
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

