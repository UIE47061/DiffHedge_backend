import os
import httpx
from bitcoinutils.keys import PrivateKey, PublicKey, P2trAddress
from bitcoinutils.transactions import Transaction, TxInput, TxOutput, TxWitnessInput
from bitcoinutils.script import Script
from bitcoinutils.utils import tapleaf_tagged_hash, tweak_taproot_pubkey, ControlBlock, get_tag_hashed_merkle_root
from dotenv import load_dotenv

load_dotenv()

# 私鑰配置
HOUSE_SECRET = int(os.getenv("HOUSE_KEY_SECRET")) if os.getenv("HOUSE_KEY_SECRET") else None
ORACLE_SECRET = int(os.getenv("ORACLE_KEY_SECRET")) if os.getenv("ORACLE_KEY_SECRET") else None

if not HOUSE_SECRET or not ORACLE_SECRET:
    raise ValueError("Please set HOUSE_KEY_SECRET and ORACLE_KEY_SECRET in .env file")

HOUSE_PRIV_KEY = PrivateKey(secret_exponent=HOUSE_SECRET)
HOUSE_PUB_KEY_HEX = HOUSE_PRIV_KEY.get_public_key().to_hex()

ORACLE_PRIV_KEY = PrivateKey(secret_exponent=ORACLE_SECRET)
ORACLE_PUB_KEY_HEX = ORACLE_PRIV_KEY.get_public_key().to_hex()

# BIP341 NUMS point
NUMS_PUBKEY_HEX = "50929b74c1a04954b78b4b6035e97a5e078a5a0f28ec96d547bfee9ace803ac0"

def to_x_only(pubkey_hex):
    if len(pubkey_hex) == 130 and pubkey_hex.startswith('04'):
        return pubkey_hex[2:66]
    elif len(pubkey_hex) == 66:
        return pubkey_hex[2:]
    return pubkey_hex

def create_contract_tree(user_pub, house_pub, oracle_pub, nonce_hex):
    """
    建立 MAST 樹狀結構 (Win, Loss, Refund)
    Win: User + Oracle
    Loss: House + Oracle
    Refund: User + House
    Structure: [[Win, Loss], Refund]
    """
    user_x = to_x_only(user_pub)
    house_x = to_x_only(house_pub)
    oracle_x = to_x_only(oracle_pub)

    def make_2of2_script(pk1, pk2, nonce):
        pks = sorted([pk1, pk2])
        return Script([
            nonce, 'OP_DROP',
            pks[0], 'OP_CHECKSIG',
            pks[1], 'OP_CHECKSIGADD',
            'OP_2', 'OP_NUMEQUAL'
        ])

    script_win = make_2of2_script(user_x, oracle_x, nonce_hex)
    script_loss = make_2of2_script(house_x, oracle_x, nonce_hex)
    script_refund = make_2of2_script(user_x, house_x, nonce_hex)

    tree = [[script_win, script_loss], script_refund]
    return tree, script_win, script_loss, script_refund

def create_2of3_address(user_pubkey_hex, nonce_hex):
    """ 建立基於 MAST 的 Taproot 地址 """
    tree, _, _, _ = create_contract_tree(user_pubkey_hex, HOUSE_PUB_KEY_HEX, ORACLE_PUB_KEY_HEX, nonce_hex)
    
    internal_pub = PublicKey(NUMS_PUBKEY_HEX)
    internal_pub_bytes = internal_pub.to_bytes()
    
    root_hash = get_tag_hashed_merkle_root(tree)
    tweak = int.from_bytes(root_hash, 'big')
    
    tweaked_pubkey, _ = tweak_taproot_pubkey(internal_pub_bytes, tweak)
    
    addr = P2trAddress(witness_program=tweaked_pubkey[:32].hex())
    return addr.to_string(), ""

async def get_utxos(address):
    base_url = "https://mempool.space/signet/api"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{base_url}/address/{address}/utxo")
            if resp.status_code != 200: return []
            return resp.json()
        except:
            return []

async def broadcast_tx(tx_hex):
    url = "https://mempool.space/signet/api/tx"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, data=tx_hex)
            return resp.text 
        except Exception as e:
            return str(e)

def get_house_address():
    return HOUSE_PRIV_KEY.get_public_key().get_segwit_address().to_string()
