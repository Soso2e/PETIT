(() => {
  'use strict';
  fetch('/api/setup/session',{credentials:'same-origin'}).then(r=>r.json()).then(s=>{
    if(!s.initialized||!s.completed||!s.authenticated){location.replace('/static/setup.html?next='+encodeURIComponent(location.pathname)+'&resume=1');return;}
    fetch('/api/setup/config').then(r=>r.json()).then(data=>{if(data.settings?.brain_enabled){const legacy=document.getElementById('chat-model-select')?.closest('.settings-card');if(legacy)legacy.hidden=true;}}).catch(()=>{});
    const panel=document.querySelector('[data-view-panel="settings"] .settings-grid');
    if(panel&&!document.getElementById('setup-settings-card')){
      const card=document.createElement('section');card.id='setup-settings-card';card.className='settings-card';
      const heading=document.createElement('h2');heading.textContent='AI・サービス接続と同期';
      const text=document.createElement('p');text.textContent='AI優先順位、Notion、Google Calendar、Gmail、TimeTree、同期エラーを管理します。';
      const link=document.createElement('a');link.href='/static/setup.html';link.textContent='接続と初期設定を開く';
      card.append(heading,text,link);panel.prepend(card);
    }
  }).catch(()=>{});
})();
