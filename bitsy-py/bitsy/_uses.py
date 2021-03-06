import logging
from fastapi.responses import JSONResponse
from fastapi import status
from eth_account.messages import defunct_hash_message
from eth_utils import to_checksum_address

from ._t import *
from ._db import *
from ._models import *
from ._crypto import *
from ._utils import *
from ._errors import *
from ._db import database
from ._config import derive_jwt

logger = logging.getLogger("bitsy.uses")


def use_case(func):
    def _use_case(*args, **kwargs):
        result = func(*args, **kwargs)
        try:
            database.commit()
            return result
        except DatabaseError as err:
            logger.error(str(err))
            database.rollback()
        return JSONResponse(
            content={"success": False},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return _use_case


def create_access_token(
    party: ThirdParty, name: Optional[str] = None
) -> AccessToken:
    token = AccessToken(uuid4(), party, name)
    token.save()
    return token


@use_case
def toggle_third_party_token(third_party_id: str, token_id: str) -> AccessToken:
    token = AccessToken.get(
        where={"third_party_id": third_party_id, "uuid": token_id}
    )
    token.toggle()
    return token


@use_case
def create_access_token_id(
    third_party_id: str, name: Optional[str] = None
) -> AccessToken:
    party = ThirdParty.get(where={"uuid": third_party_id})
    token = create_access_token(party, name)
    return token


@use_case
def delete_third_party_access_token_id(
    third_party_id: str, access_token_uuid: str
):
    token = AccessToken.get(
        where={"third_party_id": third_party_id, "uuid": access_token_uuid}
    )
    if token:
        token.delete(where={"uuid": access_token_uuid})


@use_case
def create_third_party(name: Optional[str] = None) -> ThirdParty:
    party = ThirdParty(uuid4(), name)
    party.save()
    return party


def create_access_token_for_third_party_id(
    party_id: str, name: Optional[str] = None
) -> AccessToken:
    party = ThirdParty.get(where={"uuid": party_id})
    return create_access_token_for_third_party(party, name)


@use_case
def create_third_party_account(pubkey: PublicKey) -> ThirdPartyAccount:
    party = create_third_party()
    account = create_account(pubkey, for_third_party=True)
    third_party_account = ThirdPartyAccount(party, account)
    third_party_account.save()
    return third_party_account


@use_case
def get_stats_for_account(account: Account) -> AccountStat:
    query = f"""
        SELECT 
            EXTRACT(DAYS FROM (NOW() - TO_TIMESTAMP(created_at))) AS age FROM accounts WHERE address = '{account.address}'
        UNION ALL
            SELECT COUNT(*) AS count FROM permissions WHERE account_address = '{account.address}'
    """

    results = database.query_many(query)
    return AccountStat.from_row([int(value) for value in results])


def get_stats_for_account_id(account_address: str) -> AccountStat:
    account = Account.get(where={"address": account_address})
    return get_stats_for_account(account)


@use_case
def get_settings_for_account(address: str) -> List[Setting]:
    return Setting.get_many(where={"account_address": address})


@use_case
def add_setting_to_account(
    account: Account, key: SettingKey, value: int
) -> Setting:
    setting = Setting(account, key, value)
    setting.save()
    return setting


@use_case
def verify_nonce_signature(
    nonce: str, signature: str, input: str, address: str
) -> Optional[Account]:
    defunct_digest = defunct_hash_message(text=input)
    derived = web3.eth.account.recoverHash(defunct_digest, signature=signature)
    if to_checksum_address(derived) == address:
        account = Account.get(
            where={"address": address}, fail_if_not_found=True
        )
        account.set_jwt(derive_jwt({"address": account.address}))
        return account
    return None


def add_setting_to_account_id(
    account_address: str, key: SettingKey, value: int
) -> Setting:
    account = Account.get(where={"address": account_address})
    return add_setting_to_account(account, key, value)


@use_case
def toggle_account_setting(account: Account, key: SettingKey) -> Setting:
    setting = Setting.get(
        where={"key": key.value, "account_address": account.address}
    )
    setting.toggle()
    return setting


def toggle_account_setting_id(account_address: str, key: SettingKey) -> Setting:
    account = Account.get(where={"address": account_address})
    return toggle_account_setting(account, key)


@use_case
def create_access_token_for_third_party(
    party: ThirdParty, name: Optional[str] = None
) -> AccessToken:
    token = create_access_token(party, name)
    return token


@use_case
def create_account(pubkey: PublicKey, for_third_party: bool = False) -> Account:
    account = Account(
        key_image(pubkey.to_hex()),
        pubkey.to_checksum_address(),
    )
    account.save()
    if not for_third_party:
        account.create_account_settings()
    else:
        account.create_party_settings()
    account.set_jwt(derive_jwt({"address": account.address}))
    _ = keystore.put_key(pubkey)
    return account


@use_case
def update_account_keys(
    prev_account_address: str, new_account_address: str
) -> Account:
    raise NotImplementedError


@use_case
def create_document_for_account(data: str, account: Account) -> Document:
    cid = blake3_(uuid4())
    bundle = fernet_bundle()
    ciphertext = decode(
        bundle.key.encrypt(encode(data, Encoding.UTF8)), Encoding.UTF8
    )
    document = Document(cid, DocumentBlob(ciphertext), account, bundle.key_img)
    document.save()
    _ = keystore.put_bytes(bundle.hexkey)
    return document


def create_document_for_account_id(account_address: str, data: str) -> Document:
    account = Account.get(where={"address": account_address})
    return create_document_for_account(data, account)


@use_case
def third_party_access_document_id(
    third_party_id: str, document_cid: str, account_address: str
) -> Optional[Document]:
    perm = Permission.get(
        where={
            "document_cid": document_cid,
            "third_party_id": third_party_id,
            "value": 1,
        }
    )

    if not perm:
        raise InvalidPermissionError(
            "Party({}) does not have Permission({}) for Document({})".format(
                third_party_id, PermissionKey.Read, document_cid
            )
        )

    setting = Setting.get(
        where={
            "account_address": account_address,
            "key": SettingKey.BitsyVaultDeletegation.value,
            "value": 1,
        }
    )
    if not setting:
        raise InvalidSettingError(
            "Account({}) does not have Setting({}) configured.".format(
                account_address, SettingKey.BitsyVaultDeletegation.value
            )
        )

    document = perm.document

    hexkey = keystore.get_bytes(document.key_img)
    bundle = fernet_bundle(unhexlify(hexkey))
    plaintext = decode(
        bundle.key.decrypt(encode(document.blob.data, Encoding.UTF8)),
        Encoding.UTF8,
    )

    document.set_text(plaintext)

    new_key_bytes = pbkdf2hmac_kdf(bundle.key_bytes)
    new_bundle = fernet_bundle(new_key_bytes)
    keystore.put_bytes(new_bundle.hexkey)
    new_blob = decode(
        new_bundle.key.encrypt(encode(document.blob.data, Encoding.UTF8)),
        Encoding.UTF8,
    )

    update_doc = Document.update(
        update={"key_image": new_bundle.key_img, "blob": new_blob},
        where={"cid": document.cid},
    )

    return update_doc


@use_case
def grant_perms_on_new_doc_for_third_party(
    key: PermissionKey,
    party: ThirdParty,
    data: str,
    account: Account,
    ttl: int,
) -> Permission:
    document = create_document_for_account(data, account)
    permission = Permission(
        uuid4(),
        key,
        document,
        1,
        account,
        party,
        ttl,
    )
    permission.save()
    return permission


def grant_perms_on_new_doc_for_third_party_id(
    key: PermissionKey,
    party_id: str,
    data: str,
    account_address: str,
    ttl: int = -1,
) -> Permission:
    account = Account.get(where={"address": account_address})
    party = ThirdParty.get(where={"uuid": party_id})
    return grant_perms_on_new_doc_for_third_party(
        key, party, data, account, ttl
    )


@use_case
def grant_perms_on_existing_doc_for_third_party(
    key: PermissionKey,
    party: ThirdParty,
    account: Account,
    document: Document,
    ttl: int = -1,
) -> Permission:
    perm = Permission(uuid4(), key, document, 1, account, party, ttl)
    perm.save()
    return perm


def grant_perms_on_existing_doc_for_third_party_id(
    key: PermissionKey,
    party_id: str,
    account_address: str,
    document_cid: str,
    ttl: int = -1,
) -> Permission:
    account = Account.get(where={"address": account_address})
    party = ThirdParty.get(where={"uuid": party_id})
    document = Document.get(where={"cid": document_cid})
    return grant_perms_on_existing_doc_for_third_party(
        key, party, account, document, ttl
    )


@use_case
def revoke_perms_on_existing_doc_for_third_party(
    party: ThirdParty, document_id: str, account: Account, key: PermissionKey
) -> Any:
    perm = Permission.get(
        where={
            "document_cid": document_id,
            "account_address": account.address,
            "key": key.value,
        }
    )
    if not perm:
        raise InvalidPermissionError(
            "Permission({}) does not exist for Party({}) on Document({}) belonging to Account({})".format(
                key.value, party.uuid, document_id, account.address
            )
        )

    perm.delete(where={"uuid": perm.uuid})
    return


def revoke_perms_on_existing_doc_for_third_party_id(
    party_id: str, document_id: str, account_address: str, key: SettingKey
) -> Any:
    party = ThirdParty.get(where={"uuid": party_id})
    account = Account.get(where={"address": account_address})
    return revoke_perms_on_existing_doc_for_third_party(
        party, document_id, account, key
    )


@use_case
def new_access_token_for_third_party(
    party: ThirdParty, name: Optional[str] = None
) -> AccessToken:
    token = create_access_token(party, name)
    return token


@use_case
def revoke_third_party_perms_on_account(
    key: PermissionKey, account: Account, party: ThirdParty
) -> Permission:
    perm = Permission.update(
        update={"value": 0},
        where={
            "key": key.value,
            "account_address": account.address,
            "third_party_id": party.uuid,
        },
    )
    return perm


@use_case
def list_all_third_party_perms_for_account(
    account: Account,
) -> List[Permission]:
    perms = Permission.get_many(where={"account_address": account.address})
    return perms


@use_case
def update_existing_doc_for_account(
    account: Account, blob: str, document: Document
) -> Document:

    bundle = document.update_with_new_blob(blob)
    doc = Document.update(
        update={"blob": document.blob.data, "key_image": document.key_img},
        where={"cid": document.cid, "account_address": account.address},
    )
    _ = keystore.put_bytes(bundle.hexkey)
    return doc


def update_existing_doc_for_account_id(
    account_address: str, blob: str, document_id: str
) -> Document:
    account = Account.get(where={"address": account_address})
    document = Document.get(where={"cid": document_id})
    return update_existing_doc_for_account(account, blob, document)


@use_case
def toggle_setting_for_account(account: Account) -> Setting:
    raise NotImplementedError


@use_case
def register_new_account(privkey: PublicKey) -> Account:
    raise NotImplementedError


@use_case
def create_third_party_webhook(
    party: ThirdParty, endpoint: str, type: WebhookType, name: str, active: int
) -> Webhook:
    hook = Webhook(uuid4(), party, endpoint, type, name, active)
    hook.save()
    return hook


@use_case
def delete_third_party_webhook(third_party_id: str, webhook_id: str):
    hook = Webhook.get(
        where={"third_party_id": third_party_id, "uuid": webhook_id}
    )
    if hook:
        hook.delete(where={"uuid": webhook_id})


@use_case
def toggle_third_party_webhook(third_party_id: str, webhook_id: str) -> Webhook:
    hook = Webhook.get(
        where={"uuid": webhook_id, "third_party_id": third_party_id}
    )
    hook.toggle()
    return hook


def create_third_party_webhook_id(
    party_id: str, endpoint: str, type: WebhookType, name: str, active: int
) -> Webhook:
    party = ThirdParty.get(where={"uuid": party_id})
    if not party:
        raise ResourceDoesNotExist("Party({}) not found.".format(party_id))

    return create_third_party_webhook(party, endpoint, type, name, active)
