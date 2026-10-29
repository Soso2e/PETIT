from unittest.mock import Mock
import pytest
from backend import cli_models, codex_brain, setup_store as settings
from tests.test_setup_integrations import isolated, client, admin


def test_agy_catalog_parser_does_not_invent_models():
    result=cli_models.parse_agy('Fetching available models...\nmodel-a\tModel A\nmodel-a\tModel A\n')
    assert result == [{"id":"model-a","label":"Model A"}]
    with pytest.raises(ValueError):cli_models.parse_agy('unrecognized output')


def test_codex_catalog_paginates_and_closes(monkeypatch):
    rpc=Mock()
    rpc.request.side_effect=[{"data":[{"model":"a","displayName":"A"}],"nextCursor":"next"},
                             {"data":[{"model":"b","displayName":"B"}],"nextCursor":None}]
    monkeypatch.setattr(codex_brain,"RPC",lambda:rpc)
    result=cli_models.list_models('codex')
    assert [x['id'] for x in result['models']]==['a','b'] and not result['inference_verified']
    assert rpc.request.call_args.args[1]['cursor']=='next'
    rpc.close.assert_called_once()


@pytest.mark.parametrize('provider,key',[('codex','codex_model'),('antigravity_cli','antigravity_cli_model')])
def test_models_require_admin_and_selected_model_is_saved(client,monkeypatch,provider,key):
    assert client.post('/api/setup/services/'+provider+'/models').status_code==401
    admin(client)
    monkeypatch.setattr(cli_models,'list_models',lambda p:{'provider':p,'models':[{'id':'fixture','label':'Fixture'}],'inference_verified':False})
    assert client.post('/api/setup/services/'+provider+'/models').json()['models'][0]['id']=='fixture'
    assert client.put('/api/setup/config',json={key:'fixture'}).status_code==200
    assert settings.load()[key]=='fixture'
