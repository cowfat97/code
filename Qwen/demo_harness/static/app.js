let session = null, latest = null, busy = false;
const el = id => document.getElementById(id);
function update() {
  el('send').disabled = busy;
  el('new').disabled = busy;
  el('confirm').disabled = busy || !latest || !['awaiting_confirmation','confirmed','prepared','error'].includes(latest.status) || !latest.artifacts.task || !['awaiting_confirmation','confirmed'].includes(latest.artifacts.task.status);
  el('download').disabled = busy || !latest;
}
function draw(graph) {
  el('dag').replaceChildren();
  if (!graph) return;
  const nodes = graph.nodes || [], edges = graph.edges || [];
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns,'svg');
  svg.setAttribute('width','640'); svg.setAttribute('height',String(Math.max(100,nodes.length*75)));
  const defs=document.createElementNS(ns,'defs'), marker=document.createElementNS(ns,'marker');
  for(const [k,v] of Object.entries({id:'arrow',viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:6,markerHeight:6,orient:'auto-start-reverse'}))marker.setAttribute(k,String(v));
  const arrow=document.createElementNS(ns,'path');arrow.setAttribute('d','M 0 0 L 10 5 L 0 10 z');arrow.setAttribute('fill','#8da4bc');marker.append(arrow);defs.append(marker);svg.append(defs);
  const positions = new Map(nodes.map((n,i)=>[n.id,{x:100+(i%2)*280,y:35+i*70}]));
  for(const edge of edges) {
    const a=positions.get(edge.source), b=positions.get(edge.target);
    if(!a||!b)continue;
    const line=document.createElementNS(ns,'line');
    for(const [k,v] of Object.entries({x1:a.x+100,y1:a.y+15,x2:b.x+100,y2:b.y+15,stroke:'#8da4bc','stroke-width':2,'marker-end':'url(#arrow)'}))line.setAttribute(k,String(v));
    svg.appendChild(line);
    const label=document.createElementNS(ns,'text');label.setAttribute('x',(a.x+b.x)/2+105);label.setAttribute('y',(a.y+b.y)/2+12);label.textContent=edge.type||edge.kind||'';svg.append(label);
  }
  for(const node of nodes){
    const p=positions.get(node.id), rect=document.createElementNS(ns,'rect');
    for(const [k,v] of Object.entries({x:p.x,y:p.y,width:240,height:36,rx:8,fill:'#e0ecff',stroke:'#254f99'}))rect.setAttribute(k,String(v));
    const text=document.createElementNS(ns,'text');text.setAttribute('x',p.x+8);text.setAttribute('y',p.y+23);text.textContent=node.id+' · '+(node.skill?.id||node.skill_id||'')+' @'+(node.skill?.version||'');
    svg.append(rect,text);
  }
  el('dag').appendChild(svg);
}
async function call(action,message){
  busy=true;update();el('status').textContent='处理中…';
  try{
    const response=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message,session_id:session,action,expected_revision:latest?.artifacts.task?.draft?.revision||null})});
    const data=await response.json();if(!response.ok)throw new Error(data.error||'请求失败');
    latest=data;session=data.session_id;el('history').replaceChildren();
    for(const item of data.history){const div=document.createElement('div');div.className='bubble '+item.role;div.textContent=item.content;el('history').appendChild(div);}
    el('history').scrollTop=el('history').scrollHeight;
    el('status').textContent=data.status;el('artifacts').textContent=JSON.stringify(data.artifacts,null,2);draw(data.artifacts.graph?.graph);
  }catch(error){el('status').textContent=error.message;}finally{busy=false;update();}
}
el('chat').addEventListener('submit',event=>{event.preventDefault();const text=el('message').value;el('message').value='';call('message',text);});
el('confirm').onclick=()=>call('confirm','');
el('new').onclick=()=>{session=null;latest=null;el('history').replaceChildren();el('artifacts').textContent='尚无产物';el('dag').replaceChildren();el('status').textContent='';update();};
el('download').onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(latest.artifacts,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='task-graph.json';a.click();URL.revokeObjectURL(url);};
