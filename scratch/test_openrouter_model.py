import os
import httpx

def test_model(model_name):
    api_key = "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"
    url = "https://openrouter.ai/api/v1/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model_name,
        "messages": [
            {"role": "user", "content": "Return a JSON object with key 'status' and value 'ok' representing that you are working. Return only JSON."}
        ],
        "temperature": 0.1
    }
    
    print(f"Testing model: {model_name}...")
    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=20)
        print(f"Status code: {response.status_code}")
        if response.status_code == 200:
            print("Success!")
            print(response.json()["choices"][0]["message"]["content"])
            return True
        else:
            print(f"Error response: {response.text}")
            return False
    except Exception as e:
        print(f"Exception: {e}")
        return False

def main():
    models = [
        "openrouter/free",
        "meta-llama/llama-3.2-3b-instruct:free",
        "deepseek/deepseek-v4-flash:free",
        "cognitivecomputations/dolphin-mistral-24b-venice-edition:free"
    ]
    for model in models:
        test_model(model)
        print("-" * 50)

if __name__ == "__main__":
    main()
