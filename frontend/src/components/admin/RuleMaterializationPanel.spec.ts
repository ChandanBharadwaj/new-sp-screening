import { describe, expect, it, beforeEach, vi } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import RuleMaterializationPanel, {
  type RuleMaterializationItem,
} from "./RuleMaterializationPanel.vue";

const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);

function makeItem(overrides: Partial<RuleMaterializationItem> = {}): RuleMaterializationItem {
  return {
    source: "IRAN",
    label: "US sanctions on Iran (31 CFR Part 560)",
    enabled: false,
    default_threshold: 0.55,
    phrase_strategy: "split_lists",
    updated_at: null,
    active_rules: 0,
    ...overrides,
  };
}

function mockOk(body: unknown) {
  fetchMock.mockResolvedValueOnce({
    ok: true,
    json: async () => body,
    status: 200,
    statusText: "OK",
  });
}

beforeEach(() => {
  fetchMock.mockReset();
});

describe("RuleMaterializationPanel", () => {
  it("renders label, source code, and active-rules count", () => {
    const w = mount(RuleMaterializationPanel, {
      props: {
        item: makeItem({ active_rules: 42, label: "US sanctions on Iran (31 CFR Part 560)" }),
      },
    });
    expect(w.text()).toContain("US sanctions on Iran");
    expect(w.text()).toContain("IRAN");
    expect(w.text()).toContain("42");
  });

  it("Re-materialize button is disabled when source is not enabled", () => {
    const w = mount(RuleMaterializationPanel, {
      props: { item: makeItem({ enabled: false }) },
    });
    const runBtn = w.findAll("button").find((b) => b.text().includes("Re-materialize"));
    expect(runBtn).toBeTruthy();
    expect(runBtn!.attributes("disabled")).toBeDefined();
  });

  it("Re-materialize button is enabled when source is enabled", () => {
    const w = mount(RuleMaterializationPanel, {
      props: { item: makeItem({ enabled: true }) },
    });
    const runBtn = w.findAll("button").find((b) => b.text().includes("Re-materialize"));
    expect(runBtn!.attributes("disabled")).toBeUndefined();
  });

  it("Save fires a PUT with the current draft values", async () => {
    mockOk({ source: "IRAN", enabled: true, default_threshold: 0.7, phrase_strategy: "with_aliases" });
    const w = mount(RuleMaterializationPanel, {
      props: { item: makeItem() },
    });
    // Flip the toggle, change threshold + strategy.
    await w.find('input[type="checkbox"]').setValue(true);
    await w.find('input[type="number"]').setValue("0.7");
    await w.find("select").setValue("with_aliases");

    const saveBtn = w.findAll("button").find((b) => b.text().includes("Save config"))!;
    await saveBtn.trigger("click");
    await flushPromises();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/admin/rule-materialization/IRAN");
    expect(init.method).toBe("PUT");
    const body = JSON.parse(init.body as string);
    expect(body.enabled).toBe(true);
    expect(body.default_threshold).toBe(0.7);
    expect(body.phrase_strategy).toBe("with_aliases");
  });

  it("Run fires a POST to the run endpoint and shows the counts", async () => {
    mockOk({ source: "IRAN", created: 5, updated: 0, deactivated: 0, applied: 5 });
    const w = mount(RuleMaterializationPanel, {
      props: { item: makeItem({ enabled: true }) },
    });
    const runBtn = w.findAll("button").find((b) => b.text().includes("Re-materialize"))!;
    await runBtn.trigger("click");
    await flushPromises();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/admin/rule-materialization/IRAN/run");
    expect(init.method).toBe("POST");
    expect(w.text()).toContain("Applied 5");
    expect(w.text()).toContain("created 5");
  });
});
