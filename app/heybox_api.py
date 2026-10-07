"""Normalize the website's own favourites response; never guess post IDs.

The browser produces the authenticated/signed request. Only this exact read
endpoint is accepted; request credentials and signatures never enter progress.
"""
from __future__ import annotations
import hashlib
from urllib.parse import urlparse,parse_qs,parse_qsl,urlencode,urlunparse

HOST='api.xiaoheihe.cn'
PATH='/bbs/web/profile/favours'

def matches(url):
    parsed=urlparse(url)
    return parsed.scheme=='https' and parsed.hostname==HOST and parsed.path.rstrip('/')==PATH

def parse(url,status,data):
    if not matches(url):return None
    from .platform_browser import PlatformAccessRequired
    if status in (401,403,429):raise PlatformAccessRequired('小黑盒收藏接口拒绝访问或限流；请本人完成登录或验证')
    if status!=200:raise ValueError('小黑盒收藏接口暂不可用，未登记为完整成功')
    if not isinstance(data,dict) or data.get('status')!='ok':
        raise PlatformAccessRequired('小黑盒收藏接口未返回成功，登录或验证可能未完成')
    query=parse_qs(urlparse(url).query)
    account=query.get('userid',[''])[0];owner=query.get('heybox_id',[''])[0]
    if not account or not owner or account!=owner:raise ValueError('未确认这是当前账号自己的收藏接口')
    try:offset=int(query.get('offset',['0'])[0]);limit=int(query.get('limit',['20'])[0])
    except (ValueError,TypeError):raise ValueError('收藏接口分页参数无效') from None
    if offset<0 or not 1<=limit<=100:raise ValueError('收藏接口分页超出读取范围')
    result=data.get('result')
    if isinstance(result,dict):raw=result.get('links',result.get('list'));metadata=result
    elif isinstance(result,list):raw=result;metadata={}
    else:raw=data.get('links');metadata={}
    if not isinstance(raw,list):raise ValueError('小黑盒收藏接口结构已变化；未把推荐内容或空对象当成收藏')
    items=[]
    for item in raw:
        if not isinstance(item,dict):raise ValueError('收藏接口存在未识别条目，暂停以避免漏项')
        link=item.get('link') if isinstance(item.get('link'),dict) else {}
        identifier=str(item.get('linkid') or item.get('link_id') or link.get('linkid') or item.get('id') or '')
        if not identifier.isdigit():raise ValueError('收藏接口有缺少稳定帖子ID的条目，未静默跳过')
        title=item.get('title') or link.get('title') or ('小黑盒收藏 '+identifier)
        if not isinstance(title,str):raise ValueError('收藏标题格式已变化')
        # A list description is a preview, never complete original text.
        items.append({'url':'https://www.xiaoheihe.cn/app/bbs/link/'+identifier,'title':title[:1000],
                      'remote_id':identifier,'content':{'source':'小黑盒收藏接口','original_text_complete':False}})
    next_offset=metadata.get('next_offset',offset+len(raw))
    if not isinstance(next_offset,int) or isinstance(next_offset,bool) or next_offset<offset:raise ValueError('收藏接口下一页游标无效')
    end_flag=metadata.get('has_more',data.get('has_more'))
    if not raw and (end_flag is True or type(end_flag) is int and end_flag>0):raise ValueError('收藏接口空页仍声明有后续内容；未把异常当成末尾')
    complete=not raw or end_flag is False or (type(end_flag) is int and end_flag==0)
    return {'items':items,'offset':offset,'next_offset':next_offset,'limit':limit,'count':len(raw),
            'account_fingerprint':hashlib.sha256(account.encode()).hexdigest(),
            'complete':complete,'short_page':0<len(raw)<limit,'endpoint':PATH}

class Feed:
    def __init__(self):
        self.pages=[];self.error=None;self.observed=False;self.account='';self.next_offset=0;self.seen_offsets=set();self.last_url='';self.probed=set()

    def response(self,response):
        if not matches(response.url):return
        if self.error:return
        self.observed=True
        try:
            if getattr(getattr(response,'request',None),'method','GET')!='GET':raise ValueError('收藏接口必须是只读请求')
            page=parse(response.url,response.status,response.json() if response.status==200 else {})
            if self.account and self.account!=page['account_fingerprint']:raise ValueError('读取中账号发生变化，已停止')
            self.account=page['account_fingerprint']
            if page['offset'] in self.seen_offsets:return
            if page['offset']!=self.next_offset:raise ValueError('收藏接口分页出现断点；未静默跳过中间材料')
            self.seen_offsets.add(page['offset']);self.next_offset=page['next_offset'];self.pages.append(page);self.last_url=response.url
        except Exception as error:
            self.error=error if isinstance(error,ValueError) else ValueError('无法读取收藏接口响应；未保存请求地址或签名参数')

    def take(self):
        pages=self.pages;self.pages=[]
        if pages:return pages
        self.raise_error()
        return []

    def raise_error(self):
        if self.error:raise self.error

    def verify_short_tail(self,context):
        """One read at the returned next offset, using the website's existing signature.

        Never generate signatures or probe post IDs. Rejection stops the read.
        """
        from . import adapters
        self.raise_error()
        if self.pages:return  # The website already returned another page; consume it first.
        if not self.last_url or self.next_offset in self.probed:return
        self.probed.add(self.next_offset)
        parsed=urlparse(self.last_url)
        pairs=[(k,v) for k,v in parse_qsl(parsed.query,keep_blank_values=True) if k!='offset']
        pairs.append(('offset',str(self.next_offset)))
        url=urlunparse(parsed._replace(query=urlencode(pairs)))
        adapters.public_url(url)
        try:response=context.request.get(url,timeout=20000,max_redirects=0)
        except Exception:raise ValueError('收藏接口末页核对未完成；已保存进度，不宣称全部成功') from None
        if not matches(response.url):raise ValueError('收藏接口跳转到了其他入口，已停止')
        self.response(response)
