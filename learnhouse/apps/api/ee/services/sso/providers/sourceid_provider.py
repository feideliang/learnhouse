"""
SourceID (Ruijie / 锐捷网络) OAuth 2.0 SSO provider implementation.

SourceID is commonly used in Chinese universities and enterprises.
It supports OAuth 2.0 authorization code flow (NOT OIDC compatible),
so it cannot use the existing CustomOIDCProvider.

OAuth 2.0 flow:
1. Authorize: {base_url}/oauth2.0/authorize?response_type=code&client_id=...&redirect_uri=...&state=...
2. Token: POST {base_url}/oauth2.0/accessToken (grant_type=authorization_code)
3. Profile: GET {base_url}/oauth2.0/profile?access_token=...
   Returns { id, attributes: { XM (name), GH (employee_id), DWM (department), ... } }
"""

import httpx
from typing import Optional
from urllib.parse import urlencode

from .base import SSOProvider, SSOUserProfile, SSOAuthenticationError, SSOConfigurationError


class SourceIDProvider(SSOProvider):
    """
    SourceID (锐捷) OAuth 2.0 provider.

    Connects to Ruijie's SourceID identity platform via OAuth 2.0
    authorization code flow. Not OIDC compatible — uses custom endpoints.
    """

    @property
    def provider_name(self) -> str:
        return "sourceid"

    @property
    def has_setup_portal(self) -> bool:
        # SourceID doesn't have an admin portal — config is done in LearnHouse
        return False

    def is_configured(self) -> bool:
        """SourceID is always available — config is per-organization."""
        return True

    async def get_authorization_url(
        self,
        connection_config: dict,
        redirect_uri: str,
        state: str,
    ) -> str:
        """
        Build SourceID OAuth 2.0 authorization URL.

        Args:
            connection_config: Must contain base_url, client_id, optional scope
            redirect_uri: Callback URL after authentication
            state: CSRF protection state parameter

        Returns:
            Full authorization URL to redirect the user to
        """
        base_url = connection_config.get("base_url")
        client_id = connection_config.get("client_id")
        scope = connection_config.get("scope", "")

        if not base_url or not client_id:
            raise SSOConfigurationError(
                "SourceID configuration requires base_url and client_id",
                provider=self.provider_name,
            )

        base_url = base_url.rstrip("/")
        auth_endpoint = f"{base_url}/oauth2.0/authorize"

        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
        }

        if scope:
            params["scope"] = scope

        return f"{auth_endpoint}?{urlencode(params)}"

    async def handle_callback(
        self,
        code: str,
        connection_config: dict,
    ) -> SSOUserProfile:
        """
        Exchange authorization code for user profile via SourceID OAuth 2.0.

        Steps:
        1. POST /oauth2.0/accessToken to get access_token
        2. GET /oauth2.0/profile?access_token=... to get user info

        Args:
            code: Authorization code from callback
            connection_config: Must contain base_url, client_id, client_secret, email_domain

        Returns:
            Normalized SSOUserProfile

        Raises:
            SSOAuthenticationError: If any step fails
        """
        base_url = connection_config.get("base_url", "").rstrip("/")
        client_id = connection_config.get("client_id")
        client_secret = connection_config.get("client_secret")
        email_domain = connection_config.get("email_domain", "")

        if not all([base_url, client_id, client_secret]):
            raise SSOConfigurationError(
                "SourceID configuration requires base_url, client_id, and client_secret",
                provider=self.provider_name,
            )

        token_endpoint = f"{base_url}/oauth2.0/accessToken"
        profile_endpoint = f"{base_url}/oauth2.0/profile"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                # Step 1: Exchange code for access_token
                token_response = await client.post(
                    token_endpoint,
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "redirect_uri": connection_config.get("redirect_uri", ""),
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )

                if token_response.status_code != 200:
                    error_data = (
                        token_response.json()
                        if token_response.content
                        else {"error": f"HTTP {token_response.status_code}"}
                    )
                    raise SSOAuthenticationError(
                        f"Token exchange failed: {error_data.get('error_description', error_data.get('error', 'Unknown error'))}",
                        provider=self.provider_name,
                        details=error_data,
                    )

                token_data = token_response.json()
                access_token = token_data.get("access_token")
                if not access_token:
                    raise SSOAuthenticationError(
                        "No access_token in SourceID token response",
                        provider=self.provider_name,
                        details=token_data,
                    )

                # Step 2: Get user profile
                profile_response = await client.get(
                    profile_endpoint,
                    params={"access_token": access_token},
                )

                if profile_response.status_code != 200:
                    error_data = (
                        profile_response.json()
                        if profile_response.content
                        else {"error": f"HTTP {profile_response.status_code}"}
                    )
                    raise SSOAuthenticationError(
                        f"Failed to get user profile: {error_data.get('error_description', error_data.get('error', 'Unknown error'))}",
                        provider=self.provider_name,
                        details=error_data,
                    )

                profile_data = profile_response.json()
                attributes = profile_data.get("attributes", {})
                source_id = profile_data.get("id", "")

                # Extract name from SourceID attributes
                # XM (姓名) is the full name, e.g. "张三"
                full_name = attributes.get("XM", "")

                # Split Chinese name: typically 2-3 chars, first char = surname
                first_name = None
                last_name = None
                if full_name:
                    if len(full_name) <= 1:
                        first_name = full_name
                    else:
                        # Chinese convention: first char is surname (last name), rest is given name (first name)
                        last_name = full_name[0]
                        first_name = full_name[1:]

                # SourceID doesn't have email — construct from user ID + domain
                user_id = source_id or attributes.get("GH", "")  # GH = 工号 (employee ID)
                if not user_id:
                    raise SSOAuthenticationError(
                        "Could not determine user ID from SourceID profile (no id or GH attribute)",
                        provider=self.provider_name,
                        details={"profile_data": profile_data},
                    )

                email = f"{user_id}@{email_domain}" if email_domain else user_id

                return SSOUserProfile(
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                    avatar_url=attributes.get("TXDZ") or attributes.get("AVATAR_URL"),  # 头像地址
                    provider_user_id=str(source_id) or user_id,
                    raw_attributes=profile_data,
                )

        except httpx.HTTPError as e:
            raise SSOAuthenticationError(
                f"Failed to communicate with SourceID: {str(e)}",
                provider=self.provider_name,
                details={"error": str(e)},
            )

    async def get_setup_url(
        self,
        connection_config: dict,
        return_url: str,
    ) -> Optional[str]:
        """SourceID doesn't have a setup portal."""
        return None

    def validate_config(self, config: dict) -> bool:
        """
        Validate SourceID configuration.

        Args:
            config: Must contain base_url, client_id, client_secret

        Returns:
            True if valid

        Raises:
            ValueError: If configuration is invalid
        """
        required = ["base_url", "client_id", "client_secret"]
        missing = [f for f in required if not config.get(f)]

        if missing:
            raise ValueError(
                f"Missing required SourceID configuration: {', '.join(missing)}"
            )

        base_url = config.get("base_url", "")
        if not base_url.startswith(("http://", "https://")):
            raise ValueError(
                "base_url must be a valid URL starting with http:// or https://"
            )

        return True

    def get_config_fields(self) -> list[dict]:
        """Return configuration fields for SourceID."""
        return [
            {
                "name": "base_url",
                "type": "string",
                "required": True,
                "description": "SourceID 服务器地址 (Base URL)",
                "placeholder": "https://sid.rghall.com.cn",
            },
            {
                "name": "client_id",
                "type": "string",
                "required": True,
                "description": "SourceID 应用 Client ID",
                "placeholder": "your-client-id",
            },
            {
                "name": "client_secret",
                "type": "password",
                "required": True,
                "description": "SourceID 应用 Client Secret",
                "placeholder": "your-client-secret",
            },
            {
                "name": "email_domain",
                "type": "string",
                "required": False,
                "description": "用于构造邮箱的域名后缀（SourceID 无 email 字段）",
                "placeholder": "ruishan.cc",
            },
            {
                "name": "scope",
                "type": "string",
                "required": False,
                "description": "可选 scope 参数",
                "placeholder": "openid profile",
            },
        ]
