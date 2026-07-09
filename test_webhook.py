import requests
import json

WEBHOOK_URL = "https://school-bot-function-njkftwyfzq-ew.a.run.app/"

# Імітація об'єкта Update від Telegram (тест команди /start)
payload = {
    "update_id": 100000000,
    "message": {
        "message_id": 1,
        "from": {
            "id": 1125108435, # Тестовий Telegram ID
            "is_bot": False,
            "first_name": "Test",
            "username": "test_student"
        },
        "chat": {
            "id": 1125108435,
            "type": "private"
        },
        "date": 1700000000,
        "text": "/start"
    }
}

def test_webhook():
    print(f"Відправка POST запиту на {WEBHOOK_URL}...")
    try:
        response = requests.post(
            WEBHOOK_URL, 
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=10
        )
        print(f"Статус: {response.status_code}")
        print(f"Тіло відповіді: {response.text}")
    except Exception as e:
        print(f"Помилка з'єднання: {e}")

if __name__ == "__main__":
    test_webhook()