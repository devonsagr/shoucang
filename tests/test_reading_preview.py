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
