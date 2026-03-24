"""LLM client factory and bearer-token helper."""

import time
import os
import requests
from typing import Optional, Tuple
from langchain_openai import AzureChatOpenAI
from .properties import CIRCUIT_LLM_API_APP_KEY, CIRCUIT_LLM_API_CLIENT_ID, CIRCUIT_LLM_API_ENDPOINT, CIRCUIT_LLM_API_MODEL_NAME, CIRCUIT_LLM_API_VERSION, OAUTH_ENDPOINT#, CIRCUIT_LLM_API_CLIENT_SECRET
import logging

logger = logging.getLogger(__name__)

access_token = None
last_generated = 0

def generate_bearer_token(client_id: str, client_secret: str) -> Optional[Tuple[Optional[str], int]]:
    """
    Generates a bearer token by making a POST request to the specified token URL with the provided client ID and secret.
    :param token_url: The URL to which the POST request is made to obtain the bearer token.
    :param client_id: The client ID used for authentication in the request.
    :param client_secret: The client secret used for authentication in the request.
    :return:
    """
    global access_token, last_generated
    url = OAUTH_ENDPOINT
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    auth_info = {'client_id': f'{client_id}',
                 'client_secret': f'{client_secret}',
                 'grant_type': "client_credentials"}
    response = requests.request("POST", url, data=auth_info, headers=headers)
    #log.warning(f"generate_bearer_token response_status_code: {response.status_code}")
    if response.status_code != 200:
        #log.warning(f"generate_bearer_token: {response.status_code}, {response.text}")
        return None, 0
    json_response = response.json()

    access_token = json_response['access_token']
    #log.warning(access_token)
    last_generated = time.time()


def get_llm(model_name: str = CIRCUIT_LLM_API_MODEL_NAME) -> AzureChatOpenAI:
    #if access_token is None or (last_generated + 3500) > int(time.time()):
    #    generate_bearer_token(CIRCUIT_LLM_API_CLIENT_ID, CIRCUIT_LLM_API_CLIENT_SECRET)
    os.environ["OPENAI_API_VERSION"] = CIRCUIT_LLM_API_VERSION
    os.environ["AZURE_OPENAI_ENDPOINT"] = CIRCUIT_LLM_API_ENDPOINT
    os.environ["OPENAI_API_KEY"] = "dummy_token"

    return AzureChatOpenAI(
        deployment_name=model_name,
        model_name=model_name,
        azure_endpoint=CIRCUIT_LLM_API_ENDPOINT,
        default_headers={'client-id': CIRCUIT_LLM_API_CLIENT_ID},
        #api_key=CIRCUIT_LLM_API_APP_KEY,
        api_version=CIRCUIT_LLM_API_VERSION,
        model_kwargs=dict(
            user=f'{{"appkey": "{CIRCUIT_LLM_API_APP_KEY}"}}'
        ),
        # max_tokens=100,
        temperature=0,
        streaming=True
    )