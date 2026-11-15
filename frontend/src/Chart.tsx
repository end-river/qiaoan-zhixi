import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { LineChart, ScatterChart, HeatmapChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  MarkLineComponent,
  MarkAreaComponent,
  VisualMapComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
echarts.use([
  LineChart,
  ScatterChart,
  HeatmapChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  MarkLineComponent,
  MarkAreaComponent,
  VisualMapComponent,
  CanvasRenderer,
]);
export function Chart({
  option,
  height = 300,
  group,
}: {
  option: Record<string, unknown>;
  height?: number;
  group?: string;
}) {
  const element = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  useEffect(() => {
    if (!element.current) return;
    const instance = echarts.init(element.current);
    chart.current = instance;
    if (group) {
      instance.group = group;
      echarts.connect(group);
    }
    const ro = new ResizeObserver(() => instance.resize());
    ro.observe(element.current);
    return () => {
      ro.disconnect();
      instance.dispose();
      chart.current = null;
    };
  }, [group]);
  useEffect(() => {
    chart.current?.setOption({ ...option, animationDuration: 350 }, true);
  }, [option]);
  return (
    <div
      role="img"
      aria-label="交互式监测数据图表"
      ref={element}
      style={{ height, width: "100%" }}
    />
  );
}
