import requests

def text2img(message):
    if not message:
        return "PROMPT CANNOT BE EMPTY"
    try:
        res = requests.get(f"https://gen.pollinations.ai/image/{message}")
    except Exception as e:
        return f"AN ERROR OCCURED: {e}"


if __name__ == "__main__":
    msg = input("ENTER MESSAGE:  ")
    print(text2img(msg))