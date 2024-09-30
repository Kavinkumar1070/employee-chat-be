import asyncio
import json
from datetime import date, datetime

import httpx
import requests
from fastapi import WebSocket

from chatcode.function import *


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
