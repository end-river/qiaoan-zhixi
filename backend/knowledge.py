import hashlib
import io
import os
import re
import httpx
import numpy as np
from pypdf import PdfReader
from . import storage

SEEDS = [
    {'id':'method-temperature','title':'温度补偿与统计异常：方法说明','source':'项目原创方法说明','scope':'统计方法说明，非工程鉴定规范','text':'# 温度补偿\n以用户确认的健康参考区间拟合每阶频率与温度的线性关系。观测频率减去拟合值形成残差。温度范围过窄或健康基准含异常会影响拟合。\n# 异常判定\n使用基准残差均值和协方差计算马氏距离平方，采用基准段经验 99.9% 分位为阈值。同时展示各通道 3σ 结果。经验分位不代表真实误报概率，相关性、季节外推和小样本均会影响结果。\n# 结果边界\n频率变化可能与环境、传感器或结构变化相关。不能只凭统计异常定位桥墩沉降，也不能给出法定桥梁技术状况等级。建议先核查传感器、数据质量、环境变化，再由专业人员复检。'},
    {'id':'fhwa-preservation','title':'FHWA 桥梁养护：参考资料导读','source':'https://www.fhwa.dot.gov/bridge/preservation/guide/guide.pdf','scope':'美国机构资料的中文摘要，仅作养护概念参考，不作为中国规范','text':'# 资料来源\n本条为项目编写的中文导读，原始来源为美国联邦公路管理局 Bridge Preservation Guide。应查阅原文确认上下文。\n# 养护与状态\n桥梁养护旨在延缓劣化并维持功能，行动可以按预定周期开展，也可以基于构件状况开展。统计监测可以提供核查线索，但不能代替检查与工程判断。\n# 适用边界\n此资料属于国外养护参考，不能据此给出中国法定技术状况等级或声称具体条款适用于当前桥梁。'},
    {'id':'data-quality','title':'监测数据质量与复核清单','source':'项目原创分析流程','scope':'演示工作流建议，需专业人员确认','text':'# 数据核查\n检查日期是否重复，温度与频率单位是否一致，是否存在缺测、异常尖峰或传感器更换记录。上传数据不得静默填补。\n# 参考区间\n健康参考区间需要结合巡检记录确认，不能默认前百分之七十的数据必然健康。基准拟合和后续评估必须分开，标签仅用于评估。\n# 复核顺序\n单通道尖峰应先核查设备、采集链路和数据质量。多通道持续偏移需要结合温度补偿、环境记录与现场检查形成进一步判断。所有复检建议均需专业人员审核。'}
]

def seed():
    for doc in SEEDS:
        try:
            storage.get('document', doc['id'])
        except KeyError:
            add_document(doc['title'], doc['text'], doc['source'], doc['scope'], doc['id'])

def add_document(title, text, source, scope, identifier=None):
    chunks=[]
    section='正文'
    for block in re.split(r'(?m)^(?=#)', text):
        lines=block.strip().splitlines()
        if not lines:
            continue
        if lines[0].startswith('#'):
            section=lines[0].lstrip('# ').strip()
        body='\n'.join(lines)
        for start in range(0,len(body),600):
            chunks.append({'section':section,'text':body[start:start+750]})
    if not chunks:
        raise ValueError('资料中没有可提取的文本')
    return storage.save('document',{'title':title,'source':source,'scope':scope,'chunks':chunks},identifier)

def extract(content, filename):
    if len(content)>10*1024*1024:
        raise ValueError('资料最大为 10 MB')
    if filename.lower().endswith('.pdf'):
        try:
            reader=PdfReader(io.BytesIO(content))
            if len(reader.pages)>200:
                raise ValueError('PDF 不得超过 200 页')
            text='\n'.join(f'# 第 {i+1} 页\n{p.extract_text() or ""}' for i,p in enumerate(reader.pages))
            if sum(len(p.extract_text() or '') for p in reader.pages)<50:
                raise ValueError('该 PDF 无足够可提取文本，暂不支持扫描 PDF，请提供文本型文件')
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError('PDF 读取失败，请检查文件是否损坏或加密') from exc
    elif filename.lower().endswith(('.txt','.md')):
        try:
            text=content.decode('utf-8-sig')
        except UnicodeDecodeError as exc:
            raise ValueError('请使用 UTF-8 编码的文本文件') from exc
    else:
        raise ValueError('仅支持 PDF、Markdown 和 TXT')
    if len(text)>200000:
        raise ValueError('提取文本超过 20 万字符，请拆分资料')
    return text

async def embed(texts):
    model=os.getenv('EMBEDDING_MODEL','text-embedding-v2')
    base=os.getenv('AI_BASE_URL','https://dashscope.aliyuncs.com/compatible-mode/v1').rstrip('/')
    result=[]
    missing=[]
    for i,text in enumerate(texts):
        key=hashlib.sha256((base+model+text).encode()).hexdigest()
        try:
            result.append(storage.get('embedding',key)['vector'])
        except KeyError:
            result.append(None)
            missing.append((i,text,key))
    async with httpx.AsyncClient(timeout=40) as client:
        for offset in range(0,len(missing),10):
            batch=missing[offset:offset+10]
            response=await client.post(base+'/embeddings',headers={'Authorization':'Bearer '+os.environ['AI_API_KEY']},json={'model':model,'input':[x[1] for x in batch]})
            response.raise_for_status()
            for item in response.json()['data']:
                index,_,key=batch[item['index']]
                result[index]=item['embedding']
                storage.save('embedding',{'vector':item['embedding']},key)
    return np.asarray(result,float)

def terms(text):
    text=text.lower()
    return set(re.findall(r'[a-z0-9]+|[\u4e00-\u9fff]{1,2}',text)) | {text[i:i+2] for i in range(len(text)-1) if '\u4e00'<=text[i]<='\u9fff'}

async def search(query, use_vectors=True):
    chunks=[]
    for doc in storage.listing('document'):
        for i,chunk in enumerate(doc['chunks']):
            chunks.append({'id':f'{doc["id"]}:{i}','document_id':doc['id'],'title':doc['title'],'source':doc['source'],'scope':doc['scope'],**chunk})
    if not chunks:
        return {'mode':'keyword','warning':None,'results':[]}
    query_terms=terms(query)
    lexical=np.array([len(query_terms & terms(c['text']+' '+c['title']))/max(1,len(query_terms)) for c in chunks])
    scores=lexical.copy()
    mode='keyword'
    warning=None
    if use_vectors and os.getenv('AI_API_KEY'):
        try:
            vectors=await embed([query]+[c['text'] for c in chunks])
            vectors/=np.maximum(np.linalg.norm(vectors,axis=1,keepdims=True),1e-10)
            semantic=vectors[1:]@vectors[0]
            scores=.45*lexical+.55*np.maximum(semantic,0)
            mode='hybrid'
        except Exception:
            warning='向量服务不可用，本次已明确降级为关键词检索'
    else:
        warning='未配置模型密钥，当前使用关键词检索'
    ids=np.argsort(-scores)[:5]
    results=[{**chunks[i],'score':round(float(scores[i]),4)} for i in ids if (lexical[i]>.02 if mode=='keyword' else scores[i]>.3)]
    return {'mode':mode,'warning':warning,'results':results}
