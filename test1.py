from flask import Flask, request, jsonify
import base64

app = Flask(__name__)

@app.route('/generate_link', methods=['GET'])
def generate_link():
    utm_source = request.args.get('utm_source')
    utm_medium = request.args.get('utm_medium')
    if not utm_source or not utm_medium:
        return jsonify({"error": "Both utm_source and utm_medium are required"}), 400
    params = f"utm_source={utm_source}&utm_medium={utm_medium}"
    encoded_params = base64.urlsafe_b64encode(params.encode()).decode().rstrip('=')
    generated_link = f"https://t.me/producore_bot?start={encoded_params}"
    return jsonify({"generated_link": generated_link})

if __name__ == "__main__":
    app.run(debug=True)