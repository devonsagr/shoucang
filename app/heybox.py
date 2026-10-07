"""Read the current Heybox post/article DOM; galleries are separate from prose."""
from __future__ import annotations
import re
from urllib.parse import urljoin,urlparse
from bs4 import BeautifulSoup,NavigableString

BODY_SELECTORS=('#page-bbs-link .image-text__content','#page-bbs-link .post__content','#page-bbs-link .hb-bbs-link__content','.article-content','.bbs-content','.post-content','.link-content')

def picture(node,base):
    value=node.get('data-original') or node.get('data-src') or node.get('data-lazy-src') or node.get('src') or ''
    if not value and node.get('srcset'):value=node['srcset'].split(',')[0].strip().split(' ')[0]
    if not value.strip():return None
    value=urljoin(base,value)
    if urlparse(value).scheme not in ('http','https'):return None
    return value

def markdown(node,base,missing=None):
    if isinstance(node,NavigableString):return str(node)
    if getattr(node,'name',None) in ('script','style','svg','button','form','video','source','iframe'):return ''
    if node.name=='img':
        image=picture(node,base)
        alt=re.sub(r'[\[\]\n]',' ',node.get('alt','图片')).strip()
        if image:return '\n\n!['+alt+']('+image+')\n\n'
        if missing is not None:missing.append(alt)
        return '\n\n[图片尚未加载]\n\n'
    if node.name=='br':return '\n'
    text=''.join(markdown(child,base,missing) for child in node.children)
    if node.name=='a' and node.get('href'):
        link=urljoin(base,node['href'])
        if urlparse(link).scheme in ('http','https') and text.strip():text='['+text.strip()+']('+link+')'
    if node.name in ('p','div','section','li','h1','h2','h3','h4','pre','blockquote'):text+='\n\n'
    return text

def hydrate_images(page,check_access,report=None):
    """Activate the site's normal lazy image loader without inventing source URLs."""
    from playwright.sync_api import TimeoutError as BrowserTimeout
    body=page.locator(','.join('#page-bbs-link '+s for s in ('.post__content img','.image-text__content img','.header-image__container img','.post__header-image img','.article-content img')))
    comments=page.locator('.link-comment__list > .link-comment__comment-item')
    groups=[body,*[comments.nth(i).locator('.comment-item__content img, .comment-item__content-container img, .comment-item__image-box img, .children-item__comment-content img') for i in range(min(comments.count(),20))]]
    visited=0
    for images in groups:
        for i in range(images.count()):
            if visited>=200:return
            visited+=1;image=images.nth(i)
            if any((image.get_attribute(k) or '').strip() for k in ('src','data-src','data-original','data-lazy-src','srcset')):continue
            target=image if image.is_visible() else image.locator('xpath=..')
            if not target.is_visible():continue
            check_access(page)
            if report:report({'stage':'images','message':f'正在加载原文图片 · 已检查 {visited} 张'})
            try:target.scroll_into_view_if_needed(timeout=5000)
            except BrowserTimeout:continue
            page.wait_for_timeout(300)
            check_access(page)

def parse(html,url,title):
    soup=BeautifulSoup(html,'html.parser')
    page=soup.select_one('#page-bbs-link')
    root=page.select_one('.hb-bbs-link__content') if page else None
    if root is None:root=soup.select_one('.article-content, .bbs-content, .post-content, article, .link-content')
    if root is None:raise ValueError('未辨认出小黑盒帖子正文；没有把标题、登录页或推荐流当成原文')
    post=root.select_one('.hb-bbs-image-text')
    own_post=post or root.select_one('.hb-bbs-post, .hb-bbs-video') or root
    has_video='hb-bbs-video' in own_post.get('class',[]) or bool(own_post.select('video, .hb-bbs-video, [class*="video-player"]'))
    gallery=[];missing=[];comment_missing=[]
    if post:
        node=post.select_one('.image-text__content')
        for img in post.select('.header-image__container img'):
            source=picture(img,url)
            if source and source not in gallery:gallery.append(source)
            elif not source:missing.append('顶部图片')
    else:
        node=root.select_one('.post__content .hb-article, .post__content, .article-content, .hb-article, [class*="article"][class*="content"], .rich-text, .editor-content')
        for img in root.select('.post__header-image img'):
            source=picture(img,url)
            if source and source not in gallery:gallery.append(source)
            elif not source:missing.append('顶部图片')
        if node is None and not has_video:
            node=next((n for n in root.children if getattr(n,'name',None) and not re.search(r'comment|recommend', ' '.join(n.get('class',[])),re.I)),root)
    body=markdown(node,url,missing).strip() if node else ''
    images='\n\n'.join('![图片]('+image+')' for image in gallery if image not in body)
    body=(images+'\n\n'+body).strip()
    body=re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+','\n\n',body)
    text=re.sub(r'!\[[^\]]*\]\([^)]*\)','',body).strip()
    if not body and has_video:
        video=root.select_one('video')
        poster=video.get('poster') if video else None
        body=('![视频封面]('+urljoin(url,poster)+')\n\n' if poster else '')+'[在小黑盒查看原视频]('+url+')'
    if not body or (len(text)<8 and not gallery and not has_video):raise ValueError('没有取得小黑盒正文或图集，标题不算抓取成功')
    truncated=any(re.search(r'^(展开全文|阅读全文|登录后查看)',n.get_text(strip=True)) for n in root.select('button'))
    video_only=has_video and len(text)<8
    if video_only and '在小黑盒查看原视频' not in body:body+='\n\n[在小黑盒查看原视频]('+url+')'
    comments=[]
    if page:
        for n in page.select('.link-comment__list > .link-comment__comment-item')[:20]:
            content=n.select_one('.comment-item__content-container') or n.select_one('.comment-item__content')
            author=n.select_one('.comment-item-header__info-box')
            text=markdown(content,url,comment_missing).strip() if content else ''
            for image in n.select('.comment-item__image-box img'):
                if image.find_parent(class_='comment-children-item') is None:
                    if content is not None and any(parent is content for parent in image.parents):continue
                    source=picture(image,url)
                    if not source or source not in text:text+='\n\n'+markdown(image,url,comment_missing).strip()
            if text:comments.append({'author':author.get_text(' ',strip=True) if author else '原页评论者','body':text,'url':url})
            for child in n.select('.comment-children-item')[:5]:
                if len(comments)>=20:break
                content=child.select_one('.children-item__comment-content');author=child.select_one('.children-item__comment-creator')
                text=markdown(content,url,comment_missing).strip() if content else ''
                if text:comments.append({'author':author.get_text(' ',strip=True) if author else '原页回复者','body':text,'url':url})
                if len(comments)>=20:break
            if len(comments)>=20:break
        for n in ([] if comments else page.select('.link-comment .comment-item, .link-comment .hb-bbs-comment, .comment-container .parent-comment')[:20]):
            body_text=markdown(n,url,comment_missing).strip()
            if body_text:comments.append({'author':'原页显示的评论（见原链接）','body':body_text,'url':url})
    return {'title':title,'body':body,'collection':'partial' if truncated or video_only or missing or comment_missing else 'ready',
            'content':{'source':'小黑盒官方网页正文与图集','resolved_url':url,'original_text_complete':not truncated and not video_only and not missing,
                       'missing_image_count':len(missing)+len(comment_missing),
                       'media_kind':'video_reference' if video_only else 'gallery_post' if post else 'article',
                       'gallery_count':len(gallery),'comments':comments,'comments_status':f'只存当前可辨认的 {len(comments)} 条已加载评论，非完整评论。',
                       'warning':'仅视频帖子保留原视频链接和封面，未取得字幕，不下载视频。' if video_only else f'{len(missing)+len(comment_missing)} 张图片尚未加载，已保留文本与已取得图片；可重试。' if missing or comment_missing else '正文与图集按原页顺序保存；评论仅限本次已加载并辨认的部分。'}}
