"""Create local disposable Testnet wallets; never print their seeds."""
import os
from pathlib import Path

from dotenv import dotenv_values
from xrpl.clients import JsonRpcClient
from xrpl.models.requests import AccountInfo
from xrpl.wallet import Wallet, generate_faucet_wallet

ROOT = Path(__file__).resolve().parent
ENV = ROOT / '.env'
RPC = 'https://s.altnet.rippletest.net:51234/'


def main():
    if not ENV.exists():
        buyer, merchant = Wallet.create(), Wallet.create()
        fd = os.open(ENV, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(
                f'XRPL_BUYER_SEED={buyer.seed}\n'
                f'XRPL_PAY_TO={merchant.classic_address}\n'
                f'XRPL_MERCHANT_SEED={merchant.seed}\n'
                f'XRPL_TESTNET_RPC_URL={RPC}\n'
                'XRPL_FACILITATOR_URL=https://xrpl-facilitator-testnet.t54.ai\n'
                'RELAY_SELF_URL=http://127.0.0.1:8000\n'
            )
    config = dotenv_values(ENV)
    client = JsonRpcClient(config.get('XRPL_TESTNET_RPC_URL') or RPC)
    for role, key in [('buyer', 'XRPL_BUYER_SEED'), ('merchant', 'XRPL_MERCHANT_SEED')]:
        if not config.get(key):
            continue
        wallet = Wallet.from_seed(config[key])
        result = client.request(AccountInfo(account=wallet.classic_address)).result
        if result.get('error') == 'actNotFound':
            generate_faucet_wallet(client, wallet=wallet, debug=False,
                                   faucet_host='faucet.altnet.rippletest.net')
        elif result.get('error'):
            raise RuntimeError('Testnet account lookup failed')
        result = client.request(AccountInfo(account=wallet.classic_address)).result
        print(f"{role}: {wallet.classic_address}; balance={result['account_data']['Balance']} drops")
    print('Local Testnet configuration ready. Seeds remain in ignored .env.')


if __name__ == '__main__':
    main()
