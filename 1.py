# test_connection.py
import requests

API_URL = "http://127.0.0.1:8000/"

print("Attempting to connect to the server...")

try:
    response = requests.get(API_URL, timeout=10)

    print("Connection successful!")
    print(f"Status Code: {response.status_code}")
    print("Response JSON:")
    print(response.json())

except requests.exceptions.ConnectionError as e:
    print("\n--- CONNECTION FAILED ---")
    print("Could not connect to the server.")
    print("This is likely a network, firewall, or proxy issue.")
    print(f"Error details: {e}")

except Exception as e:
    print("\n--- AN UNEXPECTED ERROR OCCURRED ---")
    print(f"Error details: {e}")