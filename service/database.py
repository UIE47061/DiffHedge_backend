import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# Supabase 配置
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Please set SUPABASE_URL and SUPABASE_KEY in environment variables")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def init_db():
    """
    初始化資料庫表格 (在 Supabase SQL Editor 中執行)
    
    CREATE TABLE IF NOT EXISTS contracts (
        id BIGSERIAL PRIMARY KEY,
        user_pubkey TEXT NOT NULL,
        deposit_address TEXT NOT NULL,
        redeem_script_hex TEXT NOT NULL,
        amount BIGINT NOT NULL,
        direction TEXT NOT NULL,
        status TEXT DEFAULT 'PENDING',
        tx_hex TEXT,
        nonce TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    
    CREATE INDEX IF NOT EXISTS idx_contracts_status ON contracts(status);
    """
    # Supabase 自動管理表格，此函數僅作為文檔說明
    print("Database initialized (using Supabase)")

def db_create_contract(user_pub, address, script_hex, amount, direction, nonce):
    try:
        result = supabase.table('contracts').insert({
            'user_pubkey': user_pub,
            'deposit_address': address,
            'redeem_script_hex': script_hex,
            'amount': amount,
            'direction': direction,
            'nonce': nonce,
            'status': 'PENDING'
        }).execute()
        
        if result.data and len(result.data) > 0:
            return result.data[0]['id']
        else:
            raise ValueError("Failed to create contract")
    except Exception as e:
        print(f"Error creating contract: {e}")
        raise

def db_get_contract(order_id):
    try:
        result = supabase.table('contracts').select('*').eq('id', order_id).execute()
        
        if result.data and len(result.data) > 0:
            return result.data[0]
        return None
    except Exception as e:
        print(f"Error getting contract: {e}")
        return None

def db_update_status(order_id, status, tx_hex=None):
    try:
        update_data = {'status': status}
        if tx_hex:
            update_data['tx_hex'] = tx_hex
        
        supabase.table('contracts').update(update_data).eq('id', order_id).execute()
    except Exception as e:
        print(f"Error updating status: {e}")
        raise

def db_delete_contract(order_id):
    try:
        supabase.table('contracts').delete().eq('id', order_id).execute()
    except Exception as e:
        print(f"Error deleting contract: {e}")
        raise

def db_get_pending_contracts():
    try:
        result = supabase.table('contracts').select('*').eq('status', 'PENDING').execute()
        return result.data if result.data else []
    except Exception as e:
        print(f"Error getting pending contracts: {e}")
        return []
