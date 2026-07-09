import time
import requests
import jwt
import sys
import os
import pandas as pd
from docx import Document as DocxDoc

# Generate a mock JWT token
mock_token = jwt.encode({"sub": "test_user_multi_file_999"}, "secret", algorithm="HS256")
headers = {
    "Authorization": f"Bearer {mock_token}"
}

api_url = "http://localhost:8000/api"

def create_test_files():
    print("Creating mock test files for all formats...")
    
    # 1. Text file
    with open("test_doc.txt", "w", encoding="utf-8") as f:
        f.write("Text File Content: Project AetherRAG is built by Rupam. [Page 1]")

    # 2. CSV file
    df_csv = pd.DataFrame([
        {"Item": "Laptop", "Price": 1200},
        {"Item": "Phone", "Price": 800}
    ])
    df_csv.to_csv("test_doc.csv", index=False)

    # 3. Excel file
    df_excel = pd.DataFrame([
        {"Topic": "Python", "Difficulty": "Easy"},
        {"Topic": "LangGraph", "Difficulty": "Advanced"}
    ])
    df_excel.to_excel("test_doc.xlsx", index=False)

    # 4. Docx file
    doc = DocxDoc()
    doc.add_paragraph("Word Document Content: The database used is PostgreSQL with pgvector.")
    doc.save("test_doc.docx")

    # 5. Image (PNG)
    # Write a minimal mock PNG structure
    with open("test_doc.png", "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")

def clean_local_test_files():
    for f in ["test_doc.txt", "test_doc.csv", "test_doc.xlsx", "test_doc.docx", "test_doc.png"]:
        if os.path.exists(f):
            os.remove(f)

def run_test():
    print("=== Start End-to-End Multi-File API Integration Test ===")
    create_test_files()
    
    file_names = ["test_doc.txt", "test_doc.csv", "test_doc.xlsx", "test_doc.docx", "test_doc.png"]
    doc_ids = []
    
    # 1. Upload all files
    print("\n1. Uploading all 5 files...")
    for filename in file_names:
        mime_type = "text/plain"
        if filename.endswith(".csv"):
            mime_type = "text/csv"
        elif filename.endswith(".xlsx"):
            mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        elif filename.endswith(".docx"):
            mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif filename.endswith(".png"):
            mime_type = "image/png"
            
        with open(filename, "rb") as f:
            files = {"file": (filename, f.read(), mime_type)}
            res = requests.post(f"{api_url}/documents/upload", headers=headers, files=files)
            
        if res.status_code != 201:
            print(f"Failed to upload {filename}: {res.status_code} - {res.text}")
            clean_local_test_files()
            sys.exit(1)
            
        data = res.json()
        doc_ids.append((filename, data["id"]))
        print(f"Uploaded {filename} -> DB Document ID: {data['id']}, Status: {data['status']}")

    # 2. Wait for Celery worker to process all documents
    print("\n2. Waiting for Celery background worker to index all documents...")
    max_polls = 15
    for i in range(max_polls):
        time.sleep(3)
        all_completed = True
        for filename, doc_id in doc_ids:
            res = requests.get(f"{api_url}/documents/{doc_id}", headers=headers)
            if res.status_code == 200:
                data = res.json()
                print(f"Poll {i+1} [{filename}]: Status = {data['status']}")
                if data["status"] == "failed":
                    print(f"ERROR: Ingestion failed for {filename} with error: {data.get('error_message')}")
                    clean_local_test_files()
                    sys.exit(1)
                elif data["status"] != "completed":
                    all_completed = False
            else:
                print(f"Failed to fetch status for {filename}")
                all_completed = False
                
        if all_completed:
            print("All documents successfully indexed!")
            break
    else:
        print("Ingestion timed out.")
        clean_local_test_files()
        sys.exit(1)

    # 3. Create Chat Thread
    print("\n3. Creating chat thread...")
    thread_res = requests.post(f"{api_url}/chat/threads", headers=headers, json={"title": "Multi-Format RAG Query"})
    if thread_res.status_code != 201:
        print(f"Failed to create chat thread: {thread_res.status_code}")
        clean_local_test_files()
        sys.exit(1)
        
    thread_data = thread_res.json()
    thread_id = thread_data["id"]
    print(f"Thread created successfully. ID: {thread_id}")

    # 4. Query RAG Pipeline (Testing retrieval across all formats)
    queries = [
        "Who built Project AetherRAG?",
        "What is the price of Laptop in the CSV table?",
        "Which difficulty is associated with Python in the Excel file?",
        "Which database is used according to the Word document?"
    ]
    
    import json
    for idx, query in enumerate(queries):
        print(f"\n4.{idx+1} Querying RAG (Streaming response): '{query}'")
        query_payload = {
            "thread_id": thread_id,
            "message": query
        }
        query_res = requests.post(f"{api_url}/chat/query", headers=headers, json=query_payload, stream=True)
        if query_res.status_code != 200:
            print(f"Failed to execute query: {query_res.status_code} - {query_res.text}")
            clean_local_test_files()
            sys.exit(1)
            
        print("Answer: ", end="", flush=True)
        answer = ""
        citations = []
        for line in query_res.iter_lines():
            if line:
                decoded_line = line.decode('utf-8').strip()
                if decoded_line.startswith("data: "):
                    try:
                        data = json.loads(decoded_line[6:])
                        if "token" in data:
                            token = data["token"]
                            answer += token
                            print(token, end="", flush=True)
                        elif "citations" in data:
                            citations = data["citations"]
                        elif "error" in data:
                            print(f"\nAPI Error: {data['error']}")
                            clean_local_test_files()
                            sys.exit(1)
                    except Exception as e:
                        pass
        print()
        print("Citations:")
        for cite in citations:
            print(f" - {cite['source']} (Page {cite['page_number']})")

    # 5. Cleanup
    print("\n5. Cleaning up database records and local test files...")
    for _, doc_id in doc_ids:
        requests.delete(f"{api_url}/documents/{doc_id}", headers=headers)
    requests.delete(f"{api_url}/chat/threads/{thread_id}", headers=headers)
    clean_local_test_files()
    print("Cleanup complete.")
    print("\n=== End-to-End Multi-File API Integration Test Succeeded! ===")

if __name__ == "__main__":
    run_test()
