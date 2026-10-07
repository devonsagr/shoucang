import pytest
from app import heybox

URL='https://www.xiaoheihe.cn/app/bbs/link/9000000000000000020'
def test_gallery_is_before_prose_and_keeps_all_five_images():
    gallery=''.join(f'<div class="header-image__item"><img src="https://cdn.example.org/{i}.jpg"></div>' for i in range(5))
    html=f'<div id="page-bbs-link"><div class="hb-bbs-link__content"><div class="hb-bbs-image-text"><div class="header-image__container">{gallery}</div><div class="image-text__content">正文第一段。<br>正文第二段。</div></div><div class="link-comment">不应混入正文的评论</div></div><aside>推荐文章</aside></div>'
    result=heybox.parse(html,URL,'帖子标题')
    assert result['collection']=='ready' and result['content']['gallery_count']==5
    for i in range(5):assert result['body'].count(f'{i}.jpg')==1
    assert result['body'].index('4.jpg')<result['body'].index('正文第一段')
    assert '不应混入正文' not in result['body'] and '推荐文章' not in result['body']

def test_article_keeps_interleaved_image_order_and_lazy_sources():
    html='<div id="page-bbs-link"><div class="hb-bbs-link__content"><article class="article-content"><p>开头原文，不能漏。</p><img data-src="https://cdn.example.org/middle.png"><p>图片之后的完整内容。</p></article></div></div>'
    r=heybox.parse(html,URL,'文章')
    assert r['body'].index('开头原文')<r['body'].index('middle.png')<r['body'].index('图片之后')
    assert r['content']['media_kind']=='article' and r['collection']=='ready'

def test_current_hb_article_excludes_author_and_topic_controls():
    html='<div id="page-bbs-link"><div class="hb-bbs-link__content"><div class="hb-bbs-post"><div class="post__container"><a>用户Lv.18</a><div class="post__content"><div class="hb-article"><p>完整作者正文第一段。</p><img src="https://cdn.example.org/a.png"><p>后半段仍保留。</p></div></div><button>话题控制</button></div></div><div class="link-comment">评论</div></div></div>'
    r=heybox.parse(html,URL,'标题')
    assert '完整作者正文' in r['body'] and '后半段仍保留' in r['body'] and 'a.png' in r['body']
    assert '用户Lv' not in r['body'] and '话题控制' not in r['body'] and '评论' not in r['body']

def test_image_only_post_is_not_rejected_as_empty_text():
    html='<div id="page-bbs-link"><div class="hb-bbs-link__content"><div class="hb-bbs-image-text"><div class="header-image__container"><img src="https://cdn.example.org/one.jpg"></div><div class="image-text__content"></div></div></div></div>'
    r=heybox.parse(html,URL,'图片帖');assert r['collection']=='ready' and r['content']['gallery_count']==1

def test_pure_video_is_an_explicit_untranscribed_reference():
    html='<div id="page-bbs-link"><div class="hb-bbs-link__content"><div class="hb-bbs-video"><video poster="https://cdn.example.org/poster.jpg"><source src="https://cdn.example.org/video.mp4"></video></div></div></div>'
    r=heybox.parse(html,URL,'视频')
    assert r['collection']=='partial' and r['content']['media_kind']=='video_reference'
    assert '在小黑盒查看原视频' in r['body'] and 'video.mp4' not in r['body'] and 'poster.jpg' in r['body']

@pytest.mark.parametrize('html',['<main><h1>只有标题</h1></main>','<div>登录后查看</div>'])
def test_title_and_login_page_are_not_content(html):
    with pytest.raises(ValueError):heybox.parse(html,URL,'标题')
def test_current_comments_and_loaded_replies_stay_separate_from_original():
    html='''<div id="page-bbs-link"><div class="hb-bbs-link__content"><div class="hb-bbs-post"><div class="post__content"><div class="hb-article"><p>原文只包含本文作者写下的内容。</p></div></div></div></div>
      <div class="link-comment__list"><div class="link-comment__comment-item"><div class="comment-item-header__info-box">评论者</div>
      <div class="comment-item__content-container"><div class="comment-item__content">这是评论正文。</div><div class="comment-item__image-box"><img src="https://cdn.example.org/comment.jpg"></div></div>
      <div class="comment-children-item"><span class="children-item__comment-creator">回复者</span><div class="children-item__comment-content">这是已加载回复。</div></div></div></div></div>'''
    from app import heybox
    result=heybox.parse(html,'https://www.xiaoheihe.cn/app/bbs/link/12345','夹具标题')
    assert '这是评论' not in result['body'] and '已加载回复' not in result['body']
    comments=result['content']['comments']
    assert len(comments)==2 and comments[0]['author']=='评论者' and 'comment.jpg' in comments[0]['body']
    assert comments[1]['body']=='这是已加载回复。' and '非完整评论' in result['content']['comments_status']
def test_comment_limit_includes_loaded_child_replies():
    from app import heybox
    card='<div class="link-comment__comment-item"><div class="comment-item__content">评论正文</div>'+''.join('<div class="comment-children-item"><div class="children-item__comment-content">已加载回复</div></div>' for _ in range(5))+'</div>'
    html='<div id="page-bbs-link"><div class="hb-bbs-link__content"><div class="post__content">实际正文，单独保存。</div></div><div class="link-comment__list">'+card*10+'</div></div>'
    result=heybox.parse(html,'https://www.xiaoheihe.cn/app/bbs/link/12345','夹具')
    assert len(result['content']['comments'])==20
