"""Entry point to start the Discharge Planning AI web server."""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("web_app:app", host="0.0.0.0", port=8000, reload=True)
