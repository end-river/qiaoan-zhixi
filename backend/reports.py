import io
from xml.sax.saxutils import escape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from . import storage

def create_report(analysis_id, conclusion='', citations=None):
    analysis=storage.get('analysis',analysis_id)
    dataset=storage.get('dataset',analysis['dataset_id'])
    s=analysis['summary']
    default=f'在指定参考区间之后的 {s["evaluated"]} 个样本中，{s["anomalies"]} 个样本超过马氏距离经验阈值。'
    default+=' 结果提示需要进一步核查的数据变化，不构成结构损伤定位或法定安全等级鉴定。'
    return storage.save('report',{'title':dataset['name']+' · 监测分析报告','analysis_id':analysis_id,'dataset_name':dataset['name'],'source':dataset['source'],'conclusion':conclusion or default,'citations':citations or [],'reference':analysis['reference'],'summary':s,'limitations':analysis['limitations'],'metrics':analysis['metrics']})

def render_pdf(title, sections):
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    buffer=io.BytesIO()
    doc=SimpleDocTemplate(buffer,pagesize=(595.28,841.89),leftMargin=45,rightMargin=45,topMargin=50,bottomMargin=48,title=title,author='桥安智析')
    body=ParagraphStyle('body',fontName='STSong-Light',fontSize=10.5,leading=18,textColor=colors.HexColor('#263c4d'),wordWrap='CJK',spaceAfter=10)
    heading=ParagraphStyle('heading',parent=body,fontSize=15,leading=23,textColor=colors.HexColor('#087f8c'),spaceBefore=16,spaceAfter=10)
    big=ParagraphStyle('title',parent=heading,fontSize=23,leading=34,spaceAfter=20)
    story=[Paragraph(escape(title),big),Paragraph('BRIDGE INSIGHT / 桥梁监测分析工作台',body),Spacer(1,12)]
    for section,content in sections:
        story.append(Paragraph(escape(section),heading))
        for line in content.split('\n'):
            if line.strip():
                story.append(Paragraph(escape(line),body))
    def footer(canvas,document):
        canvas.setStrokeColor(colors.HexColor('#dce5eb'))
        canvas.line(45,38,550,38)
        canvas.setFont('STSong-Light',9)
        canvas.drawString(45,25,'桥安智析 | 分析结果需专业人员复核')
        canvas.drawRightString(550,25,str(document.page))
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return buffer.getvalue()

def report_pdf(report):
    a=storage.get('analysis',report['analysis_id'])
    s=report['summary']
    refs='\n'.join(f'[{i+1}] {r["title"]} / {r["section"]}\n来源：{r["source"]}\n适用范围：{r["scope"]}\n证据摘录：{r["text"]}' for i,r in enumerate(report['citations'])) or '尚未附加资料引用；本报告当前结论仅依据统计分析。'
    return render_pdf(report['title'],[
        ('01 / 数据与参数',f'数据来源：{report["source"]}\n分析编号：{report["analysis_id"]}\n参考区间：{report["reference"]["start"]} 至 {report["reference"]["end"]}；参考样本 {report["reference"]["count"]} 个。\n总样本 {s["samples"]}；参考期后评估 {s["evaluated"]}；异常 {s["anomalies"]}。\n马氏距离平方阈值：{s["threshold"]:.4f}；连续三点告警起点：{s["onset"] or "未触发"}。'),
        ('02 / 分析结论（可编辑）',report['conclusion']),
        ('03 / 可核查的计算证据','\n'.join(f'{m["mode"]}：f = {m["intercept"]:.6f} + ({m["slope"]:.6f}) × T；参考残差标准差 {m["reference_std"]:.6f} Hz' for m in a['models'])),
        ('04 / 资料证据',refs),
        ('05 / 建议与局限','先核查采集链路、传感器校准记录及温度覆盖范围；必要时由专业人员组织现场复检。\n'+'\n'.join(report['limitations'])),
        ('06 / 评估范围',str(report['metrics']) if report['metrics'] else '无真实标签，不能计算误报、漏报与检测延迟。')
    ])
