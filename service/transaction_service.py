from bitcoinutils.keys import PublicKey, P2trAddress
from bitcoinutils.transactions import Transaction, TxInput, TxOutput, TxWitnessInput
from bitcoinutils.utils import tweak_taproot_pubkey, ControlBlock, get_tag_hashed_merkle_root
from .bitcoin_service import (
    HOUSE_PRIV_KEY, ORACLE_PRIV_KEY, NUMS_PUBKEY_HEX,
    to_x_only, create_contract_tree, get_utxos
)

async def build_win_path_partial_tx(contract, to_address):
    """ 構建 User Win 的部分簽名交易 (Oracle 簽名, User 留空) """
    tree, script_win, _, _ = create_contract_tree(
        contract['user_pubkey'], 
        HOUSE_PRIV_KEY.get_public_key().to_hex(), 
        ORACLE_PRIV_KEY.get_public_key().to_hex(), 
        contract['nonce']
    )
    
    internal_pub = PublicKey(NUMS_PUBKEY_HEX)
    internal_pub_bytes = internal_pub.to_bytes()
    
    root_hash = get_tag_hashed_merkle_root(tree)
    tweak = int.from_bytes(root_hash, 'big')
    _, parity = tweak_taproot_pubkey(internal_pub_bytes, tweak)
    
    cb = ControlBlock(internal_pub, tree, 0, is_odd=(parity == 1))
    
    utxos = await get_utxos(contract['deposit_address'])
    if not utxos:
        raise ValueError("Contract address has no funds")

    tx_inputs = []
    total_in = 0
    
    tweaked_pubkey, _ = tweak_taproot_pubkey(internal_pub_bytes, tweak)
    tr_addr = P2trAddress(witness_program=tweaked_pubkey[:32].hex())
    utxo_script_pubkey = tr_addr.to_script_pub_key()
    
    for utxo in utxos:
        tx_inputs.append(TxInput(utxo['txid'], utxo['vout']))
        total_in += utxo['value']

    est_vbytes = (len(tx_inputs) * 150) + (1 * 31) + 11 
    fee_rate = 2.0
    fee = int(est_vbytes * fee_rate)
    
    send_amount = total_in - fee
    if send_amount <= 0: raise ValueError(f"Insufficient funds for fee")

    dest_script = to_address.to_script_pub_key()
    tx_output = TxOutput(send_amount, dest_script)
    tx = Transaction(tx_inputs, [tx_output], has_segwit=True)

    user_x = to_x_only(contract['user_pubkey'])
    oracle_x = to_x_only(ORACLE_PRIV_KEY.get_public_key().to_hex())
    
    pubkeys = sorted([user_x, oracle_x])
    
    for i, utxo in enumerate(utxos):
        amount = utxo['value']
        
        sig_oracle = ORACLE_PRIV_KEY.sign_taproot_input(
            tx, i, [utxo_script_pubkey], [amount],
            script_path=True, tapleaf_script=script_win, tweak=False
        )
        
        sigs_map = {
            oracle_x: sig_oracle
        }
        
        witness_stack = []
        for pk in reversed(pubkeys):
            if pk in sigs_map:
                witness_stack.append(sigs_map[pk])
            else:
                witness_stack.append("")
        
        witness_elements = witness_stack + [script_win.to_hex(), cb.to_hex()]
        tx.witnesses.append(TxWitnessInput(witness_elements))

    return tx.serialize()

async def build_multisig_spend(contract, to_address):
    """ 構建 Taproot Script Path 花費交易 (House + Oracle 簽名 -> LOSS Branch) """
    tree, _, script_loss, _ = create_contract_tree(
        contract['user_pubkey'], 
        HOUSE_PRIV_KEY.get_public_key().to_hex(),
        ORACLE_PRIV_KEY.get_public_key().to_hex(), 
        contract['nonce']
    )
    
    internal_pub = PublicKey(NUMS_PUBKEY_HEX)
    internal_pub_bytes = internal_pub.to_bytes()
    
    root_hash = get_tag_hashed_merkle_root(tree)
    tweak = int.from_bytes(root_hash, 'big')
    _, parity = tweak_taproot_pubkey(internal_pub_bytes, tweak)
    
    cb = ControlBlock(internal_pub, tree, 1, is_odd=(parity == 1))
    
    utxos = await get_utxos(contract['deposit_address'])
    if not utxos:
        raise ValueError("Contract address has no funds (尚未入金?)")

    tx_inputs = []
    total_in = 0
    
    tweaked_pubkey, _ = tweak_taproot_pubkey(internal_pub_bytes, tweak)
    tr_addr = P2trAddress(witness_program=tweaked_pubkey[:32].hex())
    utxo_script_pubkey = tr_addr.to_script_pub_key()
    
    for utxo in utxos:
        tx_inputs.append(TxInput(utxo['txid'], utxo['vout']))
        total_in += utxo['value']

    est_vbytes = (len(tx_inputs) * 150) + (1 * 31) + 11 
    fee_rate = 2.0
    fee = int(est_vbytes * fee_rate)
    
    print(f"Estimated vBytes: {est_vbytes}, Fee: {fee} sats")

    send_amount = total_in - fee
    if send_amount <= 0: raise ValueError(f"Insufficient funds for fee (Need {fee}, Has {total_in})")

    dest_script = to_address.to_script_pub_key()
    tx_output = TxOutput(send_amount, dest_script)
    tx = Transaction(tx_inputs, [tx_output], has_segwit=True)

    house_x = to_x_only(HOUSE_PRIV_KEY.get_public_key().to_hex())
    oracle_x = to_x_only(ORACLE_PRIV_KEY.get_public_key().to_hex())
    
    pubkeys = sorted([house_x, oracle_x])
    
    for i, utxo in enumerate(utxos):
        amount = utxo['value']
        
        sig_house = HOUSE_PRIV_KEY.sign_taproot_input(
            tx, i, [utxo_script_pubkey], [amount],
            script_path=True, tapleaf_script=script_loss, tweak=False
        )
        
        sig_oracle = ORACLE_PRIV_KEY.sign_taproot_input(
            tx, i, [utxo_script_pubkey], [amount],
            script_path=True, tapleaf_script=script_loss, tweak=False
        )
        
        sigs_map = {
            house_x: sig_house,
            oracle_x: sig_oracle
        }
        
        witness_stack = []
        for pk in reversed(pubkeys):
            if pk in sigs_map:
                witness_stack.append(sigs_map[pk])
            else:
                witness_stack.append("") 
        
        witness_elements = witness_stack + [script_loss.to_hex(), cb.to_hex()]
        tx.witnesses.append(TxWitnessInput(witness_elements))

    return tx.serialize()

async def send_funds_from_house(to_address_obj, amount_sats):
    """ 從 House 發送資金 """
    house_pub = HOUSE_PRIV_KEY.get_public_key()
    house_addr = house_pub.get_segwit_address()
    utxos = await get_utxos(house_addr.to_string())
    
    if not utxos:
        raise ValueError("House wallet has no funds! Please fund the House address first.")

    tx_inputs = []
    total_in = 0
    for utxo in utxos:
        tx_inputs.append(TxInput(utxo['txid'], utxo['vout']))
        total_in += utxo['value']

    est_vbytes = (len(tx_inputs) * 68) + 43 + 31 + 11
    fee = int(est_vbytes * 2.0)
    change = total_in - amount_sats - fee
    
    if change < 0:
         raise ValueError(f"House insufficient funds. Has {total_in}, needs {amount_sats+fee}")

    outputs = []
    outputs.append(TxOutput(amount_sats, to_address_obj.to_script_pub_key()))
    
    if change > 546:
        outputs.append(TxOutput(change, house_addr.to_script_pub_key()))

    tx = Transaction(tx_inputs, outputs, has_segwit=True)

    p2pkh_script = house_pub.get_address().to_script_pub_key()

    for i, utxo in enumerate(utxos):
        sig = HOUSE_PRIV_KEY.sign_segwit_input(tx, i, p2pkh_script, utxo['value'])
        tx.witnesses.append(TxWitnessInput([sig, house_pub.to_hex()]))
        
    return tx.serialize()

async def build_refund_tx(contract):
    """ 構建 Taproot 退款交易 (User + House 簽名 -> Refund Branch) """
    tree, _, _, script_refund = create_contract_tree(
        contract['user_pubkey'], 
        HOUSE_PRIV_KEY.get_public_key().to_hex(),
        ORACLE_PRIV_KEY.get_public_key().to_hex(), 
        contract['nonce']
    )
    
    internal_pub = PublicKey(NUMS_PUBKEY_HEX)
    internal_pub_bytes = internal_pub.to_bytes()
    root_hash = get_tag_hashed_merkle_root(tree)
    tweak = int.from_bytes(root_hash, 'big')
    _, parity = tweak_taproot_pubkey(internal_pub_bytes, tweak)
    
    cb = ControlBlock(internal_pub, tree, 2, is_odd=(parity == 1))
    
    utxos = await get_utxos(contract['deposit_address'])
    if not utxos:
        raise ValueError("Contract address has no funds")

    tx_inputs = []
    total_in = 0
    
    tweaked_pubkey, _ = tweak_taproot_pubkey(internal_pub_bytes, tweak)
    tr_addr = P2trAddress(witness_program=tweaked_pubkey[:32].hex())
    utxo_script_pubkey = tr_addr.to_script_pub_key()
    
    for utxo in utxos:
        tx_inputs.append(TxInput(utxo['txid'], utxo['vout']))
        total_in += utxo['value']

    amount = contract['amount']
    est_vbytes = (len(tx_inputs) * 150) + (2 * 31) + 11
    fee = int(est_vbytes * 2.0)
    
    outputs = []
    msg = ""
    
    if total_in >= amount * 2:
        refund_amount = (total_in - fee) // 2
        user_addr = PublicKey(contract['user_pubkey']).get_segwit_address()
        house_addr = HOUSE_PRIV_KEY.get_public_key().get_segwit_address()
        
        outputs.append(TxOutput(refund_amount, user_addr.to_script_pub_key()))
        outputs.append(TxOutput(refund_amount, house_addr.to_script_pub_key()))
        msg = "Refunded 50/50 to User and House (Partial TX)"
    else:
        refund_amount = total_in - fee
        user_addr = PublicKey(contract['user_pubkey']).get_segwit_address()
        outputs.append(TxOutput(refund_amount, user_addr.to_script_pub_key()))
        msg = "Refunded all to User (Partial TX)"

    tx = Transaction(tx_inputs, outputs, has_segwit=True)

    user_x = to_x_only(contract['user_pubkey'])
    house_x = to_x_only(HOUSE_PRIV_KEY.get_public_key().to_hex())
    
    pubkeys = sorted([user_x, house_x])
    
    for i, utxo in enumerate(utxos):
        amount_sats = utxo['value']
        
        sig_house = HOUSE_PRIV_KEY.sign_taproot_input(
            tx, i, [utxo_script_pubkey], [amount_sats],
            script_path=True, tapleaf_script=script_refund, tweak=False
        )
        
        sigs_map = {
            house_x: sig_house
        }
        
        witness_stack = []
        for pk in reversed(pubkeys):
            if pk in sigs_map:
                witness_stack.append(sigs_map[pk])
            else:
                witness_stack.append("")
        
        witness_elements = witness_stack + [script_refund.to_hex(), cb.to_hex()]
        tx.witnesses.append(TxWitnessInput(witness_elements))

    return tx.serialize(), msg
