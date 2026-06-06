import os
import httpx


async def refresh_jobber_token() -> str:
    """Refresh the Jobber OAuth access token before each run.

    The access token expires after 60 minutes. The refresh token is permanent
    and stored in GitHub Secrets / .env. Each run fetches a fresh access token.
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.getjobber.com/api/oauth/token",
            params={
                "client_id": os.environ["JOBBER_CLIENT_ID"],
                "client_secret": os.environ["JOBBER_CLIENT_SECRET"],
                "grant_type": "refresh_token",
                "refresh_token": os.environ["JOBBER_REFRESH_TOKEN"],
            },
        )
        response.raise_for_status()
        return response.json()["access_token"]
