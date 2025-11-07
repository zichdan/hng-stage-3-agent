# check_models.py
import google.generativeai as genai
from decouple import config
import logging

# Configure a basic logger for clear output
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def list_available_gemini_models():
    """
    Connects to the Google Generative AI API using the key from the .env file
    and lists all available models, checking their compatibility with the
    'generateContent' method.
    """
    try:
        # --- Step 1: Load the API Key ---
        # This uses the same `python-decouple` library as your project to find
        # and load the GEMINI_API_KEY from your .env file.
        api_key = config("GEMINI_API_KEY", default=None)
        
        if not api_key:
            logging.error("GEMINI_API_KEY not found in your .env file.")
            logging.error("Please ensure your .env file is in the project root and contains the key.")
            return

        logging.info("API Key found. Configuring Google Generative AI client...")
        genai.configure(api_key=api_key)

        # --- Step 2: List Models and Check for 'generateContent' Support ---
        logging.info("Fetching the list of available models...\n")
        
        print("="*60)
        print("--- Available Gemini Models for Your API Key ---")
        print("="*60)
        
        found_usable_model = False
        for m in genai.list_models():
            # The 'generateContent' method is what your `GeminiContentProcessor` uses.
            # We must find a model that supports it.
            if 'generateContent' in m.supported_generation_methods:
                print(f"\nModel Name: {m.name}")
                print(f"  - Display Name: {m.display_name}")
                print(f"  - Description: {m.description}")
                print(f"  - ✅ Usable for 'generateContent': Yes")
                found_usable_model = True
        
        if not found_usable_model:
            print("\nWARNING: No models found that support the 'generateContent' method.")
            print("This might be an issue with your API key's permissions or region.")
        
        print("\n" + "="*60)
        print("ACTION: Copy a 'Model Name' from the list above (e.g., 'models/gemini-1.5-flash-001')")
        print("and paste it into the `__init__` method of your `GeminiContentProcessor` class")
        print("in `forex_agent/ai_services.py`.")
        print("="*60)

    except Exception as e:
        logging.critical(f"An unexpected error occurred: {e}", exc_info=True)
        logging.critical("This could be due to an invalid API key, network issues, or a problem with the Google AI service.")

if __name__ == "__main__":
    list_available_gemini_models()