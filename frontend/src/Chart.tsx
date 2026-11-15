import {useEffect,useRef} from 'react';
import * as echarts from 'echarts/core';
import {LineChart,ScatterChart,HeatmapChart} from 'echarts/charts';
import {GridComponent,TooltipComponent,LegendComponent,DataZoomComponent,MarkLineComponent,MarkAreaComponent,VisualMapComponent} from 'echarts/components';
import {CanvasRenderer} from 'echarts/renderers';
echarts.use([LineChart,ScatterChart,HeatmapChart,GridComponent,TooltipComponent,LegendComponent,DataZoomComponent,MarkLineComponent,MarkAreaComponent,VisualMapComponent,CanvasRenderer]);
export function Chart({option,height=300,group}:{option:Record<string,unknown>;height?:number;group?:string}){
  const element=useRef<HTMLDivElement>(null);
  const chart=useRef<echarts.ECharts|null>(null);
  useEffect(()=>{if(!element.current)return; const instance=echarts.init(element.current);chart.current=instance;if(group){instance.group=group;echarts.connect(group)}const ro=new ResizeObserver(()=>instance.resize());ro.observe(element.current);return()=>{ro.disconnect();instance.dispose();chart.current=null}},[group]);
  useEffect(()=>{chart.current?.setOption({...option,animationDuration:350},true)},[option]);
  return <div role="img" aria-label="交互式监测数据图表" ref={element} style={{height,width:'100%'}}/>;
}
export const colors=['#078b92','#3984bc','#8e78ba','#e6ac4d'];
export const base={textStyle:{fontFamily:'Microsoft YaHei, sans-serif',color:'#718494',fontSize:11},grid:{left:52,right:25,top:35,bottom:55},tooltip:{trigger:'axis',backgroundColor:'#fff',borderColor:'#dfe9ee'},legend:{top:0,icon:'roundRect',itemWidth:12,itemHeight:3,textStyle:{color:'#6c7e8a',fontSize:11}},color:colors};
