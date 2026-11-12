"""Flag editorial review candidates in report prose; never rewrite or certify it.

Usage: python review_report_language.py report.html --output review.json
Quoted source text is excluded. Technical terms are allowed in method sections.
"""
import argparse
import json
import re
from html.parser import HTMLParser
from pathlib import Path

RULES = [
    ('attribution', r'研究者(?:归纳|解释|推断)|研究团队(?:认为|发现)|专家(?:验证|认定)',
     '核实角色及其真实参与情况；通常可直接陈述发现，并在方法中说明实际分析方式。'),
    ('internal_labels', r'边界与反例|反向\s*/\s*限定声音|来源单元|方面级观点|有效判定|待测表现',
     '检查内部标签是否需要转为读者熟悉的表述；准确单位与必要定义仍须保留。'),
    ('production_notes', r'没有把[^。！？]{0,30}写成|不为[^。！？]{0,15}凑数|为通过[^。！？]{0,15}校验|脚本校验',
     '检查是否为制作过程或自我评价，宜移至方法记录，正文直接报告结果与不足。'),
    ('abstract_reasoning', r'问题层级差异|信任.{0,2}摩擦|沟通接受度|待验证的传播机制|克制归因',
     '检查概念是否有具体对象和材料解释，不能只换词掩盖推理缺口。'),
]
BLOCKS = {'h1', 'h2', 'h3', 'h4', 'p', 'li', 'th', 'td', 'summary', 'button'}
VOID = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}

class ReportText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.blocks, self.active = [], [], None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        parent = self.stack[-1] if self.stack else {'skip': False, 'section': 'report'}
        section = a.get('id', parent['section']) if tag == 'section' else parent['section']
        skip = parent['skip'] or tag in {'script','style','blockquote','pre','code'} or 'original' in a.get('class','').split() or a.get('data-language-review') == 'verbatim'
        frame = {'tag':tag,'section':section,'skip':skip}
        if tag not in VOID: self.stack.append(frame)
        if tag in BLOCKS and not skip and self.active is None:
            self.active = {'tag':tag,'depth':len(self.stack),'section':section,'parts':[]}

    def handle_data(self, data):
        if self.active and not (self.stack and self.stack[-1]['skip']):
            self.active['parts'].append(data)

    def handle_endtag(self, tag):
        if self.active and self.active['tag'] == tag and self.active['depth'] == len(self.stack):
            text = re.sub(r'\s+', ' ', ''.join(self.active['parts'])).strip()
            if text: self.blocks.append({'section':self.active['section'],'text':text})
            self.active = None
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i]['tag'] == tag:
                del self.stack[i:]
                break

def review_html(source):
    parser = ReportText(); parser.feed(source)
    candidates = []
    for idx, block in enumerate(parser.blocks):
        if block['section'] in {'method','methods','evidence','sources','appendix'}:
            continue
        for rule, pattern, action in RULES:
            matches = sorted(set(re.findall(pattern, block['text'])))
            if matches:
                candidates.append({'rule':rule,'section':block['section'],'block_index':idx,
                                   'matches':matches,'text':block['text'],'review_action':action})
    return {'type':'editorial_review_candidates','requires_semantic_review':True,
            'scope':'正文标题、说明和控件；排除逐字引文、原文区、方法与来源附录',
            'candidate_count':len(candidates),'candidates':candidates,
            'limitations':['提示不自动判错、不自动替换。','零命中不证明身份、事实归属、逻辑或语言已合格。']}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    result=review_html(args.report.read_text('utf-8-sig'))
    result['report']=str(args.report)
    text=json.dumps(result,ensure_ascii=False,indent=2)
    if args.output: args.output.write_text(text,'utf-8')
    print(text if not args.output else json.dumps({'output':str(args.output),'candidate_count':result['candidate_count']},ensure_ascii=False))

if __name__ == '__main__': main()
