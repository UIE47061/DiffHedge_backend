import traceback
from bitcoinutils.keys import PublicKey
from .database import db_update_status
from .transaction_service import build_win_path_partial_tx, build_multisig_spend
from .bitcoin_service import broadcast_tx, HOUSE_PRIV_KEY

async def execute_settlement(contract, current_difficulty, manager):
    """ 執行單一合約結算邏輯 """
    if contract['status'] not in ['PENDING', 'WAITING_USER_SIG']: 
        return {"result": "ALREADY_SETTLED", "message": f"Contract is {contract['status']}"}

    # 判定輸贏
    is_win = False
    if contract['direction'] == 'LONG' and current_difficulty > 0.05: is_win = True
    elif contract['direction'] == 'SHORT' and current_difficulty <= 0.05: is_win = True
    
    try:
        tx_hex = ""
        
        if is_win:
            user_addr_obj = PublicKey(contract['user_pubkey']).get_segwit_address()
            tx_hex = await build_win_path_partial_tx(contract, user_addr_obj)
            
            status = "WAITING_USER_SIG"
            msg = "Oracle signed. Transaction saved. Waiting for User signature."
            
            db_update_status(contract['id'], status, tx_hex)
            
            await manager.broadcast({
                "type": "ACTION_REQUIRED",
                "contract_id": contract['id'],
                "status": status,
                "tx_hex": tx_hex,
                "message": msg
            })
            
            return {
                "result": status, 
                "tx_hex": tx_hex,
                "message": msg
            }

        else:
            house_addr_obj = HOUSE_PRIV_KEY.get_public_key().get_segwit_address()
            tx_hex = await build_multisig_spend(contract, house_addr_obj)
            status = "SETTLED_LOSS"
            msg = "Oracle & House signed. Funds sent to House."
            
            txid = await broadcast_tx(tx_hex)
            
            if len(txid) != 64:
                 return {"result": "ERROR", "message": "Broadcast failed", "details": txid}

            db_update_status(contract['id'], status, tx_hex)
            
            await manager.broadcast({
                "type": "SETTLED",
                "contract_id": contract['id'],
                "result": status,
                "txid": txid
            })

            return {
                "result": status, 
                "txid": txid, 
                "tx_hex": tx_hex,
                "message": msg
            }
            
    except ValueError as ve:
        if "no funds" in str(ve):
            print(f"Skipping contract {contract['id']}: No funds.")
            return {"result": "SKIPPED", "message": "No funds in contract address."}
        else:
            print(traceback.format_exc())
            return {"result": "ERROR", "error": str(ve)}

    except Exception as e:
        print(traceback.format_exc())
        return {"result": "ERROR", "error": str(e), "traceback": traceback.format_exc(), "message": "Settlement failed"}
