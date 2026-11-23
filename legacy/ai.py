import requests

messages = [
    {
        "role": "system",
        "content": "YOUR NAME IS AXION, AN AI RUNNING IN THE TELEGRAM ENVIRONMENT. KEEP RESPONSES ALPHA AND SHORT. ONLY BE COMPREHENSIVE WHEN NECESSARY."
    }
]



people = []


def ai(message):
    print(f"Message received from {message.from_user.first_name}")

    people.append({
        "username": message.from_user.username,
        "id": message.from_user.id
    })
    if len(messages) > 10:
        for i in range(len(messages)):
            if messages[i].get("role") == "user":
                messages.pop(i)
            break

    messages.append({
        "role": "user",
        "content": f"{message.from_user.username}:{message.text}"
    })

    req = requests.post(
        f"https://text.pollinations.ai/",
        json = {
            "messages": messages
        }
    )

    print(req.status_code)

    messages.append({
        "role": "assistant",
        "content": req.text
    })

    return req.text
        
if __name__ == "__main__":
    ai("hello, how are you?")