import httpx

def main():
    url = "https://openrouter.ai/api/v1/models"
    try:
        response = httpx.get(url)
        if response.status_code == 200:
            models = response.json().get("data", [])
            print(f"Total models: {len(models)}")
            free_models = []
            for m in models:
                pricing = m.get("pricing", {})
                # Check if prompt and completion price are zero
                prompt_price = float(pricing.get("prompt", 0))
                completion_price = float(pricing.get("completion", 0))
                if prompt_price == 0.0 and completion_price == 0.0:
                    free_models.append(m)
            
            print(f"Found {len(free_models)} free models:")
            for m in sorted(free_models, key=lambda x: x.get("id")):
                print(f"  - {m.get('id')} ({m.get('name')})")
        else:
            print(f"Error: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    main()
