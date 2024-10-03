import re
import datetime
import logging
from fastapi import WebSocket
import json
import os
 
logger = logging.getLogger(__name__)
 
def get_jsonfile():
    # Get the directory where the current script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Construct the absolute path to the onboard.json file
    file_path = os.path.join(script_dir, 'onboard.json')
   
    with open(file_path, 'r') as f:
        return json.load(f)
 
 
def validate_input(field, value, datatype):
    logger.info(f"Validating {field} with value: '{value}' and datatype: {datatype}")
 
    if datatype == "string":
        return isinstance(value, str) and len(value.strip()) > 0
 
    elif datatype == "date":
        formats = [
            '%d-%m-%Y',       # 2024-09-13
            #'%d-%m-%Y',       # 13-09-2024
            #'%m-%d-%Y',       # 09-13-2024
            
            #'%m/%d/%Y',       # 09/13/2024
            #'%d/%m/%Y',       # 13/09/2024
            '%d/%m/%Y',       # 2024/09/13
            
            '%d.%m.%Y',       # 2024.09.13
            #'%d.%m.%Y',       # 13.09.2024
            
            #'%b %d, %Y',      # Sep 13, 2024
            #'%d %b %Y',       # 13 Sep 2024
            '%d %b %Y',       # 2024 Sep 13
            
            #'%d %B %Y',       # 13 September 2024
            #'%d %B',          # 13 September (day and month)
            #'%B %d, %Y',      # September 13, 2024
            #'%b %d, %Y',      # Sep 13, 2024
           
        ]
        value = value.strip()
        for fmt in formats:
            try:
                datetime.datetime.strptime(value, fmt)
                return True
            except ValueError:
                continue
        logger.warning(f"Date validation failed for value: '{value}'")
        return False
 
    elif datatype == "integer":
        return value.isdigit()
 
    elif datatype == "email":
        email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
        return re.match(email_regex, value) is not None
 
    elif datatype == "mobile":
        return value.isdigit() and len(value) == 10
 
    elif datatype == "gender":
        return value.lower() in ['male', 'female', 'other']
 
    elif datatype == "maritalstatus":
        return value.lower() in ['single', 'married', 'divorced', 'widowed']
 
    return False
 
 
async def collect_user_input(websocket: WebSocket, jsonfile, validate_input):
    res = {}
    for field, props in jsonfile.items():
        while True:
            # Prepare the message based on the datatype
            if props['datatype'] == 'gender':
                options = "Male, Female, Other"
                message = f"Please provide {field.capitalize()}. Choices are:{options}"
                print(message)
            elif props['datatype'] == 'maritalstatus':
                options = "Single, Married, Divorced, Widowed"
                message = f"Please provide {field.capitalize()}. Choices are: {options}"
            elif props['datatype'] == 'date':
                message = f"Please provide {field.capitalize()} (Format: DD-MM-YYY or similar).datatype:date"
            elif props['datatype'] == 'mobile':
                message = f"Please provide {field.capitalize()} .datatype:mobile"
            elif props['datatype'] == 'email':
                formate=r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
                message = f"Please provide {field.capitalize()} .datatype:regex ,format:{formate}"
            else:
                message = f"Please provide {field.capitalize()}: "
 
            await websocket.send_text(message)
            logger.info(f"Message sent to WebSocket: {message}")
 
            try:
                # Receive and extract the user input from JSON payload
                user_input_json = await websocket.receive_text()
                user_input_data = json.loads(user_input_json)
                user_input = user_input_data.get("message", "").strip()
                logger.info(f"Received user input: '{user_input}'")
            except Exception as e:
                logger.error(f"Error receiving input: {e}")
                await websocket.send_text("Error receiving input. Please try again.")
                continue
 
            # Validate the extracted user input
            if validate_input(field, user_input, props['datatype']):
                if props['datatype'] == "integer":
                    user_input = int(user_input)
                res[field] = user_input
                break
            else:
                error_message = f"Invalid input for {field}. Please enter a valid {props['datatype']}."
                await websocket.send_text(error_message)
                logger.info(error_message)
 
    logger.info(f"Collected Information: {res}")
    return res