import asyncio
import json
import logging
from datetime import date, datetime
from typing import Dict

import httpx
from fastapi import WebSocket

from chatcode.function import *

logger = logging.getLogger(__name__)


async def onboard_personal_details(websocket: WebSocket, details: dict):
    url = 'https://converse-chatbot-be-dev-951891e59e91.herokuapp.com/personal/employees'
    print(details)
    print(type(details))
    payload = details
    timeout_seconds = 30  # Timeout in seconds

    try:
        # Initialize HTTP client with timeout
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            response_data = response.json()
            response_data = response_data.get('detail')

            return response_data

    except httpx.HTTPStatusError as e:
        # Include response text in error message for better diagnostics
        error_message = f"HTTP error occurred: {str(e)} - Status Code: {e.response.status_code}"
        print("S", error_message)
        return error_message

    except httpx.RequestError as e:
        # General request error handling
        error_message = f"Request error occurred: {str(e)}"
        print("R", error_message)
        return error_message

    except Exception as e:
        # Catch all other unexpected errors
        error_message = f"An unexpected error occurred: {str(e)}"
        print('E', error_message)
        return error_message


def generate_html_table(data):
    if not data:
        return "<p>No data available</p>"

    # Ensure data is a list of dictionaries
    if isinstance(data, dict):
        data = [data]  # Convert single dictionary to a list

    if not data:
        return "<p>No data available</p>"

    # Extract unique headers while maintaining order
    headers = []
    for entry in data:
        for key in entry.keys():
            if key not in headers:
                headers.append(key)

    # Start building the HTML for the table with modern styles and black borders
    table = '''
    <!DOCTYPE html>
    <html>
    <head>
        <style>
           body {
            font-family: Arial, sans-serif;
            background-color: #f7f7f8;
            margin: 0;
            padding: 0;
            color: #333;
        }
        .table-wrapper {
            width: 100%; /* Make the wrapper take full width of its parent */
            max-width:990px; /* Limit the maximum width */
            overflow-x: auto; /* Allow horizontal scrolling if needed */
            margin: 20px auto; /* Center the wrapper and add margin */
           b padding: 0 15px; /* Add some padding for smaller screens */
            ox-sizing: border-box; /* Include padding in the width calculation */
        }
        table {
            width: 100%; /* Ensure table takes the full width of the wrapper */
            border-collapse: collapse;
            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
            margin: 0 auto; /* Center the table within the wrapper */
            border: 2px solid black;  /* Black border around the table */
            border-radius: 8px;
        }
        th, td {
            padding: 12px 15px;
            text-align: left;
            border: 1px solid black;  /* Black border around cells */
            white-space: nowrap; /* Prevent text from wrapping */
        }
        th {
            background-color: #3C3D37;
            color: #fff;
            text-transform: uppercase;
            border-bottom: 3px solid #000;  /* Thick bottom border for header */
        }
        tr:nth-child(even) {
            background-color: #f9f9f9;
        }
        td {
            transition: background-color 0.3s ease;
        }

        /* Responsive design adjustments */
        @media (max-width: 768px) {
            .table-wrapper {
                padding: 0 10px; /* Adjust padding for smaller screens */
            }
            table {
                font-size: 14px; /* Reduce font size for smaller screens */
            }
        }
        @media (max-width: 1024px) {
            .table-wrapper {
                padding: 0 10px; /* Adjust padding for smaller screens */
            }
            table {
                font-size: 14px; /* Reduce font size for smaller screens */
            }
        }
        </style>
    </head>
    <body>
        <div class="table-wrapper">
            <table>
                <thead>
                    <tr>'''

    # Create table headers
    for header in headers:
        table += f'<th>{header}</th>'

    table += '''
                    </tr>
                </thead>
                <tbody>'''

    # Create table rows
    for row in data:
        table += '<tr>'
        for header in headers:
            table += f'<td>{row.get(header, "N/A")}</td>'
        table += '</tr>'

    table += '''
                </tbody>
            </table>
        </div>
    </body>
    </html>
    '''

    return table


async def database_operation(websocket: WebSocket, details: dict):
    url_template = details.get('url')
    payload = details.get('payload', {})
    query_params = details.get('query_params', {})
    method = details.get('method', 'GET').upper()
    timeout_seconds = 30

    bearer_token = details.get('bearer_token')

    if not bearer_token:
        await websocket.send_text("Bearer token is missing in the request.")
        return "Bearer token is missing."

    try:
        print(url_template)
        url = url_template.format(**payload)
    except KeyError as e:
        missing_key = str(e).strip("'")
        await websocket.send_text(f"Missing value for placeholder: {missing_key}.")
        return f"Missing value for placeholder: {missing_key}."

    headers = {"Authorization": f"Bearer {bearer_token}"}

    method_dispatch = {
        "GET": lambda client: client.get(url, params=query_params, headers=headers),
        "DELETE": lambda client: client.delete(url, headers=headers),
        "PUT": lambda client: client.put(url, json=payload, headers=headers),
        "POST": lambda client: client.post(url, json=payload, headers=headers)
    }

    if method not in method_dispatch:
        await websocket.send_text(f"Unsupported HTTP method: {method}")
        return f"Unsupported HTTP method: {method}"

    try:

        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await method_dispatch[method](client)
            print('__________')
            if response.status_code == 500:
                error_message = response.text
                print(f"Error: {error_message}")
                response_data = error_message
                return response_data, payload

            if response.status_code >= 400:
                error_message = response.text
                print(f"Error: {error_message}")
                response_data = error_message
                return response_data, payload

            response_data = response.json()
            print(response_data)

            if method == 'GET':  # "Table","Return"
                html_table = generate_html_table(response_data)
                await websocket.send_text(f"{html_table}")
                return "Table", "Return"
            else:  # result and payload, result and not payload
                return response_data, payload

    except Exception as e:
        error_message = f"An unexpected error occurred: {str(e)}"
        await websocket.send_text(error_message)


# def post_permission(answer):
#     url = answer['url']
#     method = answer['method']
#     payload = answer['payload']
#     if method == 'GET':
#         response = requests.get(url)
#         permission_data = response.json()
#         return permission_data
#     elif method == 'POST':
#         response = requests.post(url, json=payload)
#         permission_data = response.json()
#         return permission_data
#     else:
#         permission_data = {"response":"method not identified"}
#         return permission_data
