import secrets
import traceback
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from bitcoinutils.keys import PublicKey, P2trAddress
from bitcoinutils.script import Script
from bitcoinutils.utils import tapleaf_tagged_hash, tweak_taproot_pubkey

from service.database import (
    db_create_contract, db_get_contract, db_delete_contract, 
    db_update_status, db_get_pending_contracts, db_get_user_contracts,
    db_get_contracts_by_status, db_get_waiting_signature_contracts
)
from service.bitcoin_service import (
    create_2of3_address, get_utxos, broadcast_tx, 
    get_house_address, to_x_only, NUMS_PUBKEY_HEX,
    HOUSE_PRIV_KEY, ORACLE_PRIV_KEY
)
from service.transaction_service import send_funds_from_house, build_refund_tx
from service.settlement_service import execute_settlement
from service.websocket_manager import manager

router = APIRouter(prefix="/api", tags=["contract"])

class ContractRequest(BaseModel):
    user_pubkey: str
    amount: int
    direction: str

class SettleRequest(BaseModel):
    contract_id: int
    current_difficulty: float

class MatchRequest(BaseModel):
    contract_id: int

class RefundRequest(BaseModel):
    contract_id: int

class CancelRequest(BaseModel):
    contract_id: int

class SettleAllRequest(BaseModel):
    current_difficulty: float

@router.get("/stats")
def stats():
    house_addr = get_house_address()
    return {
        "difficulty": 0.047, 
        "hashprice_sats": 220000.0,
        "house_address": house_addr
    }

@router.get("/contract/{contract_id}")
def get_contract_api(contract_id: int):
    contract = db_get_contract(contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    return contract

@router.get("/contracts/user/{user_pubkey}")
def get_user_contracts(user_pubkey: str):
    """獲取特定用戶的所有合約"""
    contracts = db_get_user_contracts(user_pubkey)
    return {"contracts": contracts, "count": len(contracts)}

@router.get("/contracts/status/{status}")
def get_contracts_by_status(status: str):
    """獲取特定狀態的所有合約"""
    contracts = db_get_contracts_by_status(status)
    return {"contracts": contracts, "count": len(contracts)}

@router.get("/contracts/waiting-signature")
def get_waiting_signature_contracts():
    """獲取所有等待用戶簽名的合約"""
    contracts = db_get_waiting_signature_contracts()
    return {"contracts": contracts, "count": len(contracts)}

@router.post("/create_contract")
def create_contract(req: ContractRequest):
    nonce_hex = secrets.token_hex(4)
    address, script_hex = create_2of3_address(req.user_pubkey, nonce_hex)
    
    contract_id = db_create_contract(req.user_pubkey, address, script_hex, req.amount, req.direction, nonce_hex)
    
    return {
        "status": "success",
        "contract_id": contract_id,
        "deposit_address": address,
        "amount": req.amount,
        "message": f"Please deposit {req.amount} sats to this address. House will match 1:1."
    }

@router.post("/match")
async def match_contract(req: MatchRequest):
    try:
        contract = db_get_contract(req.contract_id)
        if not contract: raise HTTPException(404, "Contract not found")
        
        utxos = await get_utxos(contract['deposit_address'])
        current_balance = sum(u['value'] for u in utxos)
        
        if current_balance < contract['amount']:
            return {"status": "waiting_for_user", "message": "User deposit not detected yet."}
            
        if current_balance >= contract['amount'] * 2:
            return {"status": "already_matched", "message": "Contract is already fully funded."}

        user_x = to_x_only(contract['user_pubkey'])
        house_x = to_x_only(HOUSE_PRIV_KEY.get_public_key().to_hex())
        oracle_x = to_x_only(ORACLE_PRIV_KEY.get_public_key().to_hex())
        
        pubkeys = sorted([user_x, house_x, oracle_x])
        nonce_hex = contract['nonce']
        
        script_elements = [
            nonce_hex, 'OP_DROP',
            pubkeys[0], 'OP_CHECKSIG',
            pubkeys[1], 'OP_CHECKSIGADD',
            pubkeys[2], 'OP_CHECKSIGADD',
            'OP_2', 'OP_NUMEQUAL'
        ]
        tapleaf_script = Script(script_elements)
        
        leaf_hash = tapleaf_tagged_hash(tapleaf_script)
        internal_pub = PublicKey(NUMS_PUBKEY_HEX)
        internal_pub_bytes = internal_pub.to_bytes()
        tweak = int.from_bytes(leaf_hash, 'big')
        tweaked_pubkey, _ = tweak_taproot_pubkey(internal_pub_bytes, tweak)
        
        multisig_addr = P2trAddress(witness_program=tweaked_pubkey[:32].hex())
        
        match_amount = contract['amount'] 
        
        tx_hex = await send_funds_from_house(multisig_addr, match_amount)
        txid = await broadcast_tx(tx_hex)
        
        if len(txid) != 64:
             return {"status": "error", "error": "Broadcast failed", "details": txid}

        await manager.broadcast({
            "type": "MATCHED",
            "contract_id": req.contract_id,
            "txid": txid,
            "message": f"House matched {match_amount} sats."
        })

        return {
            "status": "matched", 
            "txid": txid, 
            "message": f"House matched {match_amount} sats (1:1 Odds). Contract is now live!"
        }
    except Exception as e:
        print(traceback.format_exc())
        return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

@router.post("/refund")
async def refund_contract(req: RefundRequest):
    try:
        contract = db_get_contract(req.contract_id)
        if not contract: raise HTTPException(404, "Contract not found")
        
        if contract['status'] != 'PENDING':
             return {"result": "ALREADY_SETTLED", "message": f"Contract is {contract['status']}"}

        tx_hex, msg = await build_refund_tx(contract)
        
        status = "WAITING_USER_SIG_REFUND"
        db_update_status(req.contract_id, status, tx_hex)
        
        return {
            "status": "waiting_user_sig",
            "tx_hex": tx_hex,
            "message": msg + ". Waiting for User signature."
        }
    except Exception as e:
        print(traceback.format_exc())
        return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

@router.post("/cancel_contract")
def cancel_contract(req: CancelRequest):
    db_delete_contract(req.contract_id)
    return {"status": "cancelled", "contract_id": req.contract_id}

@router.post("/settle")
async def settle_contract(req: SettleRequest):
    contract = db_get_contract(req.contract_id)
    if not contract: raise HTTPException(404, "Contract not found")
    return await execute_settlement(contract, req.current_difficulty, manager)

@router.post("/settle_all")
async def settle_all_contracts(req: SettleAllRequest):
    contracts = db_get_pending_contracts()

    results = []
    for contract in contracts:
        res = await execute_settlement(contract, req.current_difficulty, manager)
        results.append({"id": contract['id'], "result": res})
            
    return {"summary": results, "count": len(results)}
