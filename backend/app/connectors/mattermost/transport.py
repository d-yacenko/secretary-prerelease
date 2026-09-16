from dataclasses import dataclass
from typing import Any, Protocol, Self

import httpx

from app.connectors.mattermost.constants import MATTERMOST_USERS_IDS_BATCH_SIZE
from app.connectors.mattermost.errors import (
    MattermostEndpointNotFoundError,
    MattermostSecurityError,
    MattermostTransportError,
    MattermostUnauthorizedError,
    MattermostWriteDefiniteError,
    MattermostWriteUncertainError,
)


@dataclass(frozen=True)
class MattermostPostsPage:
    order: list[str]
    posts: dict[str, dict[str, Any]]
    provider_saturated: bool = False


class MattermostTransport(Protocol):
    def get_me(self) -> dict[str, Any]:
        ...

    def close(self) -> None:
        ...

    def list_my_channels(self) -> list[dict[str, Any]]:
        ...

    def list_my_teams(self) -> list[dict[str, Any]]:
        ...

    def list_team_channels_for_user(self, team_id: str, user_id: str) -> list[dict[str, Any]]:
        ...

    def get_posts_page(
        self,
        channel_id: str,
        page: int,
        per_page: int,
    ) -> MattermostPostsPage:
        ...

    def get_posts_after(
        self,
        channel_id: str,
        after_post_id: str,
        per_page: int,
    ) -> MattermostPostsPage:
        ...

    def get_posts_before(
        self,
        channel_id: str,
        before_post_id: str,
        per_page: int,
    ) -> MattermostPostsPage:
        ...

    def get_posts_since(
        self,
        channel_id: str,
        since_ms: int,
    ) -> MattermostPostsPage:
        ...

    def get_users_by_ids(self, user_ids: list[str]) -> list[dict[str, Any]]:
        ...

    def create_post(
        self,
        channel_id: str,
        message: str,
        pending_post_id: str,
        root_id: str | None = None,
    ) -> dict[str, Any]:
        ...


class MattermostHttpTransport:
    def __init__(
        self,
        base_url: str,
        access_token: str,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._access_token = access_token
        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx.Client(follow_redirects=False, timeout=30.0)

    def close(self) -> None:
        if self._owns_http_client:
            self._http_client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def get_me(self) -> dict[str, Any]:
        return self._request_json("GET", "/api/v4/users/me")

    def list_my_channels(self) -> list[dict[str, Any]]:
        payload = self._request_json("GET", "/api/v4/users/me/channels")
        if not isinstance(payload, list):
            raise MattermostTransportError("mattermost channels response malformed")
        return payload

    def list_my_teams(self) -> list[dict[str, Any]]:
        payload = self._request_json("GET", "/api/v4/users/me/teams")
        if not isinstance(payload, list):
            raise MattermostTransportError("mattermost teams response malformed")
        return payload

    def list_team_channels_for_user(self, team_id: str, user_id: str) -> list[dict[str, Any]]:
        path = f"/api/v4/users/{user_id}/teams/{team_id}/channels"
        payload = self._request_json("GET", path)
        if not isinstance(payload, list):
            raise MattermostTransportError("mattermost team channels response malformed")
        return payload

    def get_posts_page(
        self,
        channel_id: str,
        page: int,
        per_page: int,
    ) -> MattermostPostsPage:
        path = f"/api/v4/channels/{channel_id}/posts"
        payload = self._request_json(
            "GET",
            path,
            params={"page": page, "per_page": per_page},
        )
        return self._parse_posts_payload(payload)

    def get_posts_after(
        self,
        channel_id: str,
        after_post_id: str,
        per_page: int,
    ) -> MattermostPostsPage:
        path = f"/api/v4/channels/{channel_id}/posts"
        payload = self._request_json(
            "GET",
            path,
            params={"after": after_post_id, "page": 0, "per_page": per_page},
        )
        return self._parse_posts_payload(payload)

    def get_posts_before(
        self,
        channel_id: str,
        before_post_id: str,
        per_page: int,
    ) -> MattermostPostsPage:
        _validate_posts_before_params(channel_id, before_post_id, per_page)
        path = f"/api/v4/channels/{channel_id}/posts"
        payload = self._request_json(
            "GET",
            path,
            params={"before": before_post_id, "page": 0, "per_page": per_page},
        )
        return self._parse_posts_payload(payload)

    def get_posts_since(
        self,
        channel_id: str,
        since_ms: int,
    ) -> MattermostPostsPage:
        path = f"/api/v4/channels/{channel_id}/posts"
        payload = self._request_json("GET", path, params={"since": since_ms})
        page = self._parse_posts_payload(payload)
        saturated = len(page.order) >= 1000
        return MattermostPostsPage(
            order=page.order,
            posts=page.posts,
            provider_saturated=saturated,
        )

    def get_users_by_ids(self, user_ids: list[str]) -> list[dict[str, Any]]:
        if not user_ids:
            return []
        results: list[dict[str, Any]] = []
        for start in range(0, len(user_ids), MATTERMOST_USERS_IDS_BATCH_SIZE):
            batch = user_ids[start : start + MATTERMOST_USERS_IDS_BATCH_SIZE]
            payload = self._request_json("POST", "/api/v4/users/ids", json_body=batch)
            if not isinstance(payload, list):
                raise MattermostTransportError("mattermost users response malformed")
            results.extend(payload)
        return results

    def create_post(
        self,
        channel_id: str,
        message: str,
        pending_post_id: str,
        root_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "channel_id": channel_id,
            "message": message,
            "pending_post_id": pending_post_id,
        }
        if root_id:
            body["root_id"] = root_id
        payload = self._request_write_json("POST", "/api/v4/posts", json_body=body)
        if not isinstance(payload, dict):
            raise MattermostWriteUncertainError("mattermost create post response malformed")
        return payload

    def _request_write_json(
        self,
        method: str,
        path: str,
        json_body: Any | None = None,
    ) -> Any:
        url = self._build_api_url(path)
        headers = {"Authorization": f"Bearer {self._access_token}"}
        try:
            response = self._http_client.request(
                method,
                url,
                headers=headers,
                json=json_body,
            )
        except httpx.RequestError as exc:
            raise MattermostWriteUncertainError("mattermost write request failed") from exc

        if 300 <= response.status_code < 400:
            raise MattermostSecurityError("mattermost redirect rejected")
        if 400 <= response.status_code < 500:
            raise MattermostWriteDefiniteError("mattermost write rejected")
        if response.status_code >= 500:
            raise MattermostWriteUncertainError("mattermost write response uncertain")

        if not response.content:
            raise MattermostWriteUncertainError("mattermost create post response malformed")
        try:
            return response.json()
        except ValueError as exc:
            raise MattermostWriteUncertainError("mattermost create post response malformed") from exc

    def _request_json(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
    ) -> Any:
        url = self._build_api_url(path)
        headers = {"Authorization": f"Bearer {self._access_token}"}
        try:
            response = self._http_client.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
            )
        except httpx.RequestError as exc:
            raise MattermostTransportError("mattermost request failed") from exc

        if 300 <= response.status_code < 400:
            raise MattermostSecurityError("mattermost redirect rejected")
        if response.status_code == 404:
            raise MattermostEndpointNotFoundError("mattermost endpoint not found")
        if response.status_code in (401, 403):
            raise MattermostUnauthorizedError("mattermost authorization failed")
        if response.status_code >= 400:
            raise MattermostTransportError("mattermost request rejected")

        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise MattermostTransportError("mattermost response malformed") from exc

    def _build_api_url(self, path: str) -> str:
        if not path.startswith("/"):
            raise MattermostSecurityError("mattermost api path must be relative")
        return f"{self._base_url}{path}"

    @staticmethod
    def _parse_posts_payload(payload: Any) -> MattermostPostsPage:
        if not isinstance(payload, dict):
            raise MattermostTransportError("mattermost posts response malformed")
        order = payload.get("order")
        posts = payload.get("posts")
        if not isinstance(order, list) or not isinstance(posts, dict):
            raise MattermostTransportError("mattermost posts response malformed")
        normalized_order = [str(item) for item in order]
        normalized_posts = {str(key): value for key, value in posts.items()}
        return MattermostPostsPage(order=normalized_order, posts=normalized_posts)


def _validate_posts_before_params(
    channel_id: str,
    before_post_id: str,
    per_page: int,
) -> None:
    if not str(channel_id).strip():
        raise ValueError("channel_id is required")
    if not str(before_post_id).strip():
        raise ValueError("before_post_id is required")
    if per_page <= 0:
        raise ValueError("per_page must be positive")


class FakeMattermostTransport:
    def __init__(
        self,
        me: dict[str, Any] | None = None,
        channels: list[dict[str, Any]] | None = None,
        teams: list[dict[str, Any]] | None = None,
        team_channels: dict[tuple[str, str], list[dict[str, Any]]] | None = None,
        posts_by_channel: dict[str, list[dict[str, Any]]] | None = None,
        users_by_id: dict[str, dict[str, Any]] | None = None,
        redirect_on_me: bool = False,
        unauthorized_on_me: bool = False,
        my_channels_not_found: bool = False,
        create_post_error: Exception | None = None,
        create_post_response: Any | None = None,
    ) -> None:
        self.me = me or {
            "id": "user-1",
            "username": "alice",
            "display_name": "Alice",
            "email": "alice@example.com",
        }
        self.channels = list(channels or [])
        self.teams = list(teams or [])
        self.team_channels = dict(team_channels or {})
        self.posts_by_channel: dict[str, list[dict[str, Any]]] = {
            key: list(value) for key, value in (posts_by_channel or {}).items()
        }
        self.users_by_id = dict(users_by_id or {})
        self.redirect_on_me = redirect_on_me
        self.unauthorized_on_me = unauthorized_on_me
        self.my_channels_not_found = my_channels_not_found
        self.create_post_error = create_post_error
        self.create_post_response = create_post_response
        self.close_invoked = False
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []
        self.create_post_calls: list[dict[str, Any]] = []

    def close(self) -> None:
        self.close_invoked = True

    def get_me(self) -> dict[str, Any]:
        self.calls.append(("GET", "/api/v4/users/me", None))
        if self.redirect_on_me:
            raise MattermostSecurityError("mattermost redirect rejected")
        if self.unauthorized_on_me:
            raise MattermostUnauthorizedError("mattermost authorization failed")
        return dict(self.me)

    def list_my_channels(self) -> list[dict[str, Any]]:
        self.calls.append(("GET", "/api/v4/users/me/channels", None))
        if self.my_channels_not_found:
            raise MattermostEndpointNotFoundError("mattermost endpoint not found")
        return [dict(channel) for channel in self.channels]

    def list_my_teams(self) -> list[dict[str, Any]]:
        self.calls.append(("GET", "/api/v4/users/me/teams", None))
        return [dict(team) for team in self.teams]

    def list_team_channels_for_user(self, team_id: str, user_id: str) -> list[dict[str, Any]]:
        self.calls.append(
            (
                "GET",
                f"/api/v4/users/{user_id}/teams/{team_id}/channels",
                None,
            )
        )
        return [dict(channel) for channel in self.team_channels.get((team_id, user_id), [])]

    def get_posts_page(
        self,
        channel_id: str,
        page: int,
        per_page: int,
    ) -> MattermostPostsPage:
        params = {"page": page, "per_page": per_page}
        self.calls.append(("GET", f"/api/v4/channels/{channel_id}/posts", params))
        posts = self._newest_first_posts(channel_id)
        start = page * per_page
        end = start + per_page
        slice_posts = posts[start:end]
        return self._build_page(slice_posts)

    def get_posts_after(
        self,
        channel_id: str,
        after_post_id: str,
        per_page: int,
    ) -> MattermostPostsPage:
        params = {"after": after_post_id, "page": 0, "per_page": per_page}
        self.calls.append(("GET", f"/api/v4/channels/{channel_id}/posts", params))
        posts = self._oldest_first_posts(channel_id)
        after_index = -1
        for index, post in enumerate(posts):
            if str(post.get("id")) == after_post_id:
                after_index = index
                break
        slice_posts = posts[after_index + 1 : after_index + 1 + per_page]
        return self._build_page(slice_posts)

    def get_posts_before(
        self,
        channel_id: str,
        before_post_id: str,
        per_page: int,
    ) -> MattermostPostsPage:
        _validate_posts_before_params(channel_id, before_post_id, per_page)
        params = {"before": before_post_id, "page": 0, "per_page": per_page}
        self.calls.append(("GET", f"/api/v4/channels/{channel_id}/posts", params))
        posts = self._oldest_first_posts(channel_id)
        before_index = -1
        for index, post in enumerate(posts):
            if str(post.get("id")) == before_post_id:
                before_index = index
                break
        older_posts = posts[:before_index] if before_index > 0 else []
        slice_posts = older_posts[-per_page:] if older_posts else []
        return self._build_page(slice_posts)

    def get_posts_since(
        self,
        channel_id: str,
        since_ms: int,
    ) -> MattermostPostsPage:
        params = {"since": since_ms}
        self.calls.append(("GET", f"/api/v4/channels/{channel_id}/posts", params))
        posts = [
            post
            for post in self._oldest_first_posts(channel_id)
            if int(post.get("update_at") or post.get("create_at") or 0) >= since_ms
        ]
        saturated = len(posts) >= 1000
        if saturated:
            posts = posts[:1000]
        page = self._build_page(posts)
        return MattermostPostsPage(
            order=page.order,
            posts=page.posts,
            provider_saturated=saturated,
        )

    def get_users_by_ids(self, user_ids: list[str]) -> list[dict[str, Any]]:
        self.calls.append(("POST", "/api/v4/users/ids", {"ids": user_ids}))
        return [
            dict(self.users_by_id[user_id])
            for user_id in user_ids
            if user_id in self.users_by_id
        ]

    def create_post(
        self,
        channel_id: str,
        message: str,
        pending_post_id: str,
        root_id: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "channel_id": channel_id,
            "message": message,
            "pending_post_id": pending_post_id,
        }
        if root_id:
            payload["root_id"] = root_id
        self.calls.append(("POST", "/api/v4/posts", payload))
        self.create_post_calls.append(payload)
        if self.create_post_error is not None:
            raise self.create_post_error
        if self.create_post_response is not None:
            if isinstance(self.create_post_response, dict):
                return dict(self.create_post_response)
            return self.create_post_response
        post_id = f"created-{len(self.create_post_calls)}"
        post = {
            "id": post_id,
            "channel_id": channel_id,
            "user_id": str(self.me.get("id") or "user-1"),
            "message": message,
            "pending_post_id": pending_post_id,
            "create_at": 1_700_000_000_000,
            "update_at": 1_700_000_000_000,
            "type": "",
            "root_id": root_id or "",
            "file_ids": [],
        }
        self.posts_by_channel.setdefault(channel_id, []).append(dict(post))
        return dict(post)

    def _channel_posts(self, channel_id: str) -> list[dict[str, Any]]:
        return [dict(post) for post in self.posts_by_channel.get(channel_id, [])]

    def _newest_first_posts(self, channel_id: str) -> list[dict[str, Any]]:
        return sorted(
            self._channel_posts(channel_id),
            key=lambda item: int(item.get("create_at") or 0),
            reverse=True,
        )

    def _oldest_first_posts(self, channel_id: str) -> list[dict[str, Any]]:
        return sorted(
            self._channel_posts(channel_id),
            key=lambda item: int(item.get("create_at") or 0),
        )

    def _build_page(self, posts: list[dict[str, Any]]) -> MattermostPostsPage:
        order = [str(post["id"]) for post in posts]
        payload = {str(post["id"]): post for post in posts}
        return MattermostPostsPage(order=order, posts=payload)
