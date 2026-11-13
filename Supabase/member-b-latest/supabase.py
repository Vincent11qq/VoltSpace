import os
import httpx
from dotenv import load_dotenv

load_dotenv()


class SupabaseConnection:

    def _init_(self):
        self.url = os.getenv("VOLTSPACE_SUPABASE_URL", "").rstrip("/")
        self.key = (
            os.getenv("VOLTSPACE_SUPABASE_SERVICE_KEY")
            or os.getenv("VOLTSPACE_SUPABASE_KEY", "")
        )

        if not self.url or not self.key:
            raise ValueError("Supabase URL or API key is missing.")

        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }

    def test_connection(self):
        endpoint = f"{self.url}/rest/v1/"

        try:
            response = httpx.get(
                endpoint,
                headers=self.headers,
                timeout=15,
            )

            if response.status_code < 400:
                return {
                    "connected": True,
                    "message": "Supabase connection successful."
                }

            return {
                "connected": False,
                "message": response.text
            }

        except httpx.HTTPError as error:
            return {
                "connected": False,
                "message": str(error)
            }

if _name_ == "_main_":
    supabase = SupabaseConnection()
    print(supabase.test_connection())