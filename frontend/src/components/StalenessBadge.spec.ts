import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import StalenessBadge from "./StalenessBadge.vue";

describe("StalenessBadge", () => {
  it("renders 'today' when days=0", () => {
    const w = mount(StalenessBadge, { props: { days: 0, severity: "green" } });
    expect(w.text()).toBe("today");
    expect(w.classes().join(" ")).toContain("bg-emerald-100");
  });

  it("renders singular '1 day old' when days=1", () => {
    const w = mount(StalenessBadge, { props: { days: 1, severity: "green" } });
    expect(w.text()).toBe("1 day old");
  });

  it("renders plural for days>1", () => {
    const w = mount(StalenessBadge, { props: { days: 14, severity: "amber" } });
    expect(w.text()).toBe("14 days old");
    expect(w.classes().join(" ")).toContain("bg-amber-100");
  });

  it("renders 'never loaded' when days=null", () => {
    const w = mount(StalenessBadge, { props: { days: null, severity: "gray" } });
    expect(w.text()).toBe("never loaded");
    expect(w.classes().join(" ")).toContain("bg-slate-100");
  });

  it("uses red styling for red severity", () => {
    const w = mount(StalenessBadge, { props: { days: 90, severity: "red" } });
    expect(w.classes().join(" ")).toContain("bg-red-100");
  });
});
