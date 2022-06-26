from fastapi import FastAPI, Request, Response, APIRouter
from fastapi.routing import APIRoute
from pydantic import BaseModel
import strawberry

from ._models import PermKey, SettingKey
from ._uses import *
from ._utils import *

# IMPORTANT: FastAPI module should match definitions in _models.py


@strawberry.type
class AccessToken(BaseModel):
    uuid: str


@strawberry.type
class ThirdParty(BaseModel):
    uuid: str
    access_token: AccessToken


@strawberry.type
class Account(BaseModel):
    pubkey: str


@strawberry.type
class DocumentBlob(BaseModel):
    data: str


@strawberry.type
class Document(BaseModel):
    cid: str
    blob: DocumentBlob
    account: Account


@strawberry.type
class Permission(BaseModel):
    uuid: str
    key: str
    document: Document
    value: int
    account: Account
    third_party: ThirdParty


@strawberry.type
class Setting(BaseModel):
    id: int
    key: SettingKey
    value: int


class DummyRoute(APIRoute):
    def get_route_handler(self) -> Callable:
        original_route_handler = super().get_route_handler()

        async def dummy_route_handler(request: Request) -> Response:
            response = await original_route_handler
            return response

        return dummy_route_handler


app = FastAPI()


# IMPORTANT: Routes have same name as the use-case they serve, but are prefixed with 'route_'


@app.get("/")
def route_index():
    return "Welcome to Bitsy!"


@app.post("/third-party")
async def route_create_third_party(request: Request):
    party: ThirdParty = create_third_party()
    return party


@app.post("/document")
async def route_create_document(request: Request):
    body = await request.json()
    doc: Document = create_document_for_account_id(
        body["pubkey"], encode_utf8(body["data"])
    )
    return doc


@app.post("/access_token")
async def route_new_access_token_for_third_party(request: Request):
    body = await request.json()
    third_party_id = body["uuid"]
    token: AccessToken = create_access_token_for_third_party_id(third_party_id)
    return token


@app.post("/account")
async def route_create_account(request: Request):
    body = await request.json()
    account: Account = create_account(body["pubkey"])
    return account


@app.post("/permission")
async def route_grant_perms_on_doc_for_third_party(request: Request):

    body = await request.json()

    doc_id = body.get("document_id")
    doc = body.get("data")

    if doc_id is None:
        perm: Permission = grant_perms_on_new_doc_for_third_party_id(
            PermKey(body["key"]),
            body["party_id"],
            encode_utf8(doc),
            body["pubkey"],
        )
        return perm

    perm: Permission = grant_perms_on_existing_doc_for_third_party_id(
        PermKey(body["key"]),
        body["party_id"],
        body["pubkey"],
        body["document_id"],
    )
    return perm


router = APIRouter(route_class=DummyRoute)

app.include_router(router)