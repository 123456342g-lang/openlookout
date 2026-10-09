// OpenLookout 生成的填表脚本：只填写，不提交。提交按钮永远由你自己按。
(function(){
  const DATA = [{"_doc": "dzfp_26115964120722875680.pdf.txt", "发票号码": "26115964120722875680", "开票日期": "2026年09月23日", "销售方名称": "上海泰坦科技股份有限公司", "价税合计": "1530.00", "税额": "176.02"}, {"_doc": "dzfp_26116341459815699637.pdf.txt", "发票号码": "26116341459815699637", "开票日期": "2026年09月21日", "销售方名称": "北京博瑞生物科技有限公司", "价税合计": "356.00", "税额": "40.96"}];            // 每张待报发票一行
  const MAP = {"发票号码": "发票号码", "开票日期": "开票日期", "销售方名称": "销售方名称", "价税合计": "价税合计", "税额": "税额"};              // 网页字段标签 -> 数据列
  const idx = Number(new URLSearchParams(location.search).get('ol_row') || 0);
  const row = DATA[idx]; if(!row) return;
  const labels = Array.from(document.querySelectorAll('label'));
  let filled = 0;
  for (const [label, col] of Object.entries(MAP)) {
    const lb = labels.find(l => l.textContent.replace(/[\s：:*]/g,'') === label);
    const input = lb && (lb.htmlFor ? document.getElementById(lb.htmlFor) : lb.querySelector('input'));
    if (!input) continue;
    input.value = row[col] ?? ''; input.dispatchEvent(new Event('input', {bubbles:true})); filled++;
  }
  document.body.setAttribute('data-ol-filled', String(filled));
})();
