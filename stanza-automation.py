import os
import time
import requests
import json
from datetime import datetime

USERNAME = "postmams"
PASSWORD = "gma7mams"
MODE = "CEA_608"
PROCESS_DATE = datetime.now().strftime("%Y%m%d%H%M%S")

BASE_URL = "http://localhost:7000/api"

#SPEECH-TO-TEXT VARIABLES
LANGUAGE = "tl"
MODEL = "LargeV2"
TRANSCRIPTION_PROMPT = (
    "Transcribe only clearly spoken Tagalog, including English words with a Tagalog accent."
    "Ignore background noise, music, silence, and unclear speech."
)

ENCODED_PROMPT = requests.utils.quote(TRANSCRIPTION_PROMPT)

#EXPORT-CAPTION VARIABLES
EXPORT_FORMAT = "scc"
FRAMERATE = "29.97"
DROP_FRAME = "true"

# API URLs (one-liners)
JWT_URL = f"{BASE_URL}/users/jwt-login"
PROJECT_URL = f"{BASE_URL}/projects/add-project"
SET_STATUS_URL = f"{BASE_URL}/projects/{{}}/set-status"
SET_ASSIGNEE_URL = f"{BASE_URL}/projects/{{}}/set-assignee"
OPERATIONS_URL = f"{BASE_URL}/operations"
SPEECH_TO_TEXT_URL = f"{BASE_URL}/projects/{{}}/{{}}/local-speech-to-text?language={LANGUAGE}&model={MODEL}"
#SPEECH_TO_TEXT_URL = f"{BASE_URL}/projects/{{}}/{{}}/local-speech-to-text?language={LANGUAGE}&model={MODEL}&prompt={ENCODED_PROMPT}"
EXPORT_CAPTION_URL = f"{BASE_URL}/projects/{{}}/export-caption-file?programIds={{}}&format={EXPORT_FORMAT}&framerate={FRAMERATE}&dropFrame={DROP_FRAME}&exportLocationId={{}}"

# Location-specific constants
LOCATION_ALIAS_MAPPING = {
    "pmc_stanza_tst": {
        "alias": "PMC_STANZA_TST",
        "exportLocation_id": "4718bd34-110a-4997-a107-35a42efc5dc3"
    },
    "stanza_transit": {
        "alias": "STANZA_TRANSIT",
        "exportLocation_id": "adec4715-c87c-4d4c-9e32-da86b4d4d7a9"
    }
}

# Global Variables
jwt_token = None
LOCATION_ALIAS = None


def print_curl_command(method, url, headers, data=None):
    """Prints a cURL command for debugging purposes."""
    command = f"curl -X {method} '{url}'"
    for header, value in headers.items():
        command += f" -H '{header}: {value}'"
    if data:
        command += f" -d '{json.dumps(data)}'"
    print("cURL Command:", command)


def get_jwt_token():
    """Authenticates and retrieves the JWT token."""
    global jwt_token
    payload = {"userName": USERNAME, "password": PASSWORD}
    headers = {'Accept': 'text/plain', 'Content-Type': 'application/json-patch+json'}
    
    print_curl_command("POST", JWT_URL, headers, payload)
    
    try:
        response = requests.post(JWT_URL, json=payload, headers=headers)
        response.raise_for_status()
        jwt_token = response.json()['token']
    except requests.exceptions.RequestException as e:
        print(f"Error: Failed to get JWT token. {str(e)}")
        jwt_token = None


def create_project(file):
    """Creates a new project using the provided file."""
    file_name_without_extension = os.path.splitext(os.path.basename(file))[0]
    filename_with_extension = os.path.basename(file)
    project_data = {
        "projectName": f"AI-{file_name_without_extension}-{PROCESS_DATE}",
        "videoFile": f"::{LOCATION_ALIAS}\\AUTOMATION\\SOURCE\\{filename_with_extension}",
        "subtitleFile": "",
        "dueDateTime": "",
        "configuration": {
            "mode": MODE,
            "maxLineCount": 2,
            "maxLineLength": 28,
            "minDuration": 0,
            "maxDuration": 0,
            "maxCPS": 0
        },
        "language": "fil-PH"
    }
    headers = {"Authorization": f"Bearer {jwt_token}", "Accept": "text/plain"}
    
    print_curl_command("POST", PROJECT_URL, headers, project_data)
    
    try:
        response = requests.post(PROJECT_URL, json=project_data, headers=headers)
        response.raise_for_status()
        project_info = response.json()
        return project_info['id'], project_info['programs'][0]['id']
    except requests.exceptions.RequestException as e:
        print(f"Error: Failed to create project for {file}. {str(e)}")
        return None, None


def set_project_assignee(project_id):
    """Sets the assignee for a project."""
    assignee_data = {
        "projectId": project_id,
        "newAssigneeId": "edce626a-e85d-4faa-b96c-c55198e70c7e"  # Hardcoded assignee ID
    }
    headers = {"Authorization": f"Bearer {jwt_token}", "Content-Type": "application/json"}
    
    print_curl_command("POST", SET_ASSIGNEE_URL.format(project_id), headers, assignee_data)
    
    try:
        response = requests.post(SET_ASSIGNEE_URL.format(project_id), json=assignee_data, headers=headers)
        response.raise_for_status()
        print(f"Assignee set successfully for project {project_id}.")
        return True
    except requests.exceptions.RequestException as e:
        print(f"Error: Failed to set assignee for project {project_id}. {str(e)}")
        return False


def set_project_status(project_id):
    """Sets the status for a project."""
    status_data = {
        "projectId": project_id,
        "newStatusId": "804d5879-e2c2-45be-95da-6e0f89c4bb38"
    }
    headers = {"Authorization": f"Bearer {jwt_token}", "Accept": "application/json"}
    
    print_curl_command("POST", SET_STATUS_URL.format(project_id), headers, status_data)
    
    try:
        response = requests.post(SET_STATUS_URL.format(project_id), json=status_data, headers=headers)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        print(f"Error: Failed to set status for project {project_id}. {str(e)}")
        return False


def process_speech_to_text(project_id, program_id):
    """Initiates the speech-to-text process for a project."""
    headers = {"Authorization": f"Bearer {jwt_token}", "Accept": "text/plain"}
    time.sleep(10)  # Wait before starting the process
    
    print_curl_command("POST", SPEECH_TO_TEXT_URL.format(project_id, program_id), headers)
    
    try:
        response = requests.post(SPEECH_TO_TEXT_URL.format(project_id, program_id), headers=headers)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        print(f"Error: Failed to start speech-to-text for project {project_id}. {str(e)}")
        return False


def check_speech_to_text_status(project_id):
    """Checks the status of the speech-to-text process."""
    headers = {"Authorization": f"Bearer {jwt_token}", "Accept": "application/json"}
    
    while True:
        try:
            response = requests.get(OPERATIONS_URL, headers=headers)
            response.raise_for_status()
            operations = response.json()
            
            for operation in operations:
                if operation['projectId'] == project_id and operation['operationType'] == 'LocalSpeechToText':
                    progress = operation.get('progress', 0)
                    if progress == 100:
                        return True
                    else:
                        time.sleep(10)  # Wait before checking again
        except requests.exceptions.RequestException as e:
            print(f"Error: Failed to check speech-to-text status for project {project_id}. {str(e)}")
            return False


def export_caption(project_id, program_id, exportLocation_id):
    """Exports the caption file for a project."""
    headers = {"Authorization": f"Bearer {jwt_token}", "Accept": "text/plain"}
    
    print_curl_command("POST", EXPORT_CAPTION_URL.format(project_id, program_id, exportLocation_id), headers)
    
    try:
        response = requests.post(EXPORT_CAPTION_URL.format(project_id, program_id, exportLocation_id), headers=headers)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        print(f"Error: Failed to export caption for project {project_id}. {str(e)}")
        return False


def main(file):
    """Main function to process a file."""
    global LOCATION_ALIAS
    
    # Determine LOCATION_ALIAS and exportLocation_id based on file path
    location_key = None
    for key in LOCATION_ALIAS_MAPPING:
        if key in file.lower():
            location_key = key
            break
    
    if not location_key:
        print("Error: File path must contain either 'pmc_stanza_tst' or 'stanza_transit'.")
        return
    
    LOCATION_ALIAS = LOCATION_ALIAS_MAPPING[location_key]["alias"]
    exportLocation_id = LOCATION_ALIAS_MAPPING[location_key]["exportLocation_id"]
    
    print(f"LOCATION_ALIAS set to {LOCATION_ALIAS}")
    print(f"exportLocation_id set to {exportLocation_id}")
    
    # Authenticate and process
    get_jwt_token()
    if not jwt_token:
        print("Failed to authenticate.")
        return
    
    project_id, program_id = create_project(file)
    if not project_id or not program_id:
        return
    
    if not set_project_status(project_id):
        return
    
    if not set_project_assignee(project_id):
        return
    
    if not process_speech_to_text(project_id, program_id):
        return
    
    if not check_speech_to_text_status(project_id):
        return
    
    if not export_caption(project_id, program_id, exportLocation_id):
        return
    
    print(f"File {file} processed successfully.")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        file = sys.argv[1]
        main(file)
    else:
        print("Usage: stanza-automation.py <filepath>")