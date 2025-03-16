from app import app

if __name__ == "__main__":
    # For local development without Gunicorn
    app.run(host="0.0.0.0", port=5000, debug=True)