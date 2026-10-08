from app import reading_preview,store
from test_automatic_collection import local

TEXT='工具把原文和用户批注分开保存，避免混淆作者的说法与个人理解。\n\n图片按原文位置保存，顶部的五张图片也是同一条材料的一部分。\n\n后来再次导入时，只给新材料排队，已有材料的原文、批注和处理状态保持。\n\n来源指纹可以阻止已经彻底删除的帖子再次被误当成新材料。\n\n真正整理材料时，应依据原文和用户自己的批注，不把速览当成结论。'

def test_preview_uses_original_sentences_without_model_or_notes():
    item={'body':TEXT,'notes':'仅在我的备注中的秘密目的','summary':'AI编出的不同看法','content':{},'platform':'heybox'}
    r=reading_preview.make(item)
    assert r and r['method']=='extractive' and not r['model_used'] and r['reading_only']
    assert '秘密目的' not in r['text'] and 'AI编出的' not in r['text']
    assert all(sentence in TEXT for sentence in r['text'].splitlines())

def test_short_posts_and_video_references_do_not_get_fake_summaries():
    assert reading_preview.make({'body':'短帖直接阅读原文。','content':{}}) is None
    assert reading_preview.make({'body':TEXT,'content':{'media_kind':'video_reference'}}) is None

def test_gallery_does_not_hide_the_list_excerpt():
    body='\n\n'.join(f'![图片](capture-id/images/{i}.png)' for i in range(5))+'\n\n这是图片后面的作者原文。'
    assert reading_preview.excerpt({'body':body,'content':{}})=='这是图片后面的作者原文。'

def test_reading_preview_is_not_saved_or_exported(local):
    client,_=local
    mid=client.post('/api/materials',json={'url':'https://x.com/i/status/76001','text':TEXT}).json()['id']
    before=store.get(mid)
    detail=client.get('/api/materials/'+mid).json()
    assert detail['reading_preview']['reading_only']
    assert store.get(mid)==before and 'reading_preview' not in store.markdown(before)
    payload=client.post('/api/materials/'+mid+'/push-preview',json={'destination':'markdown'}).json()['payload']
    assert 'reading_preview' not in payload and '原文摘录' not in payload['markdown']


def test_context_is_kept_instead_of_picking_repeated_dates_and_platform_fragments():
    text='《合成冒险》是一款多人协作游戏，这篇报道介绍了开发团队宣布的主机发行计划。\n\n也将会登陆Switch 2平台\n\n游戏将在10月16号在Switch发售，新增的协作模式允许四名玩家共同挑战关卡。\n\nSwitch平台支持跨平台存档。'*2
    result=reading_preview.make({'body':text,'content':{}})
    assert result['text'].startswith('《合成冒险》')
    assert '发行计划' in result['text'] and '协作模式' in result['text']
    assert result['source']=='原文导读' and not result['model_used']

def test_fragments_and_ui_noise_do_not_become_a_fake_subject():
    text='收藏 123\n\n也将登陆Switch平台，发布日期会稍后公布。\n\n此外会推出新的音乐版本，更多信息将在后续公布。'*3
    assert reading_preview.make({'body':text,'content':{}}) is None
