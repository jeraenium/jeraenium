# jeraenium

**A living garden, greenhouse, sensor network, and design system for more intelligent, ecological, human-scale growing.**

`jeraenium` is a long-form practical experiment in building a garden that can be observed, understood, cared for, automated, narrated, and gradually made more alive.

It begins with a real garden and greenhouse.  
It grows through sensors, plant records, local data, small electronics, horticultural experiments, repair, reuse, and careful observation.  
It eventually becomes a wider architecture for humane, AI-assisted growing systems.

Not a gadget garden.  
Not a fake “smart home” for plants.  
Not automation for the sake of automation.

The aim is simpler and better:

> **A greenhouse that learns with you.**

---

## Why this exists

Gardens already contain intelligence.

Plants respond to light, water, temperature, humidity, pathogens, pests, pruning, stress, soil, season, and one another. A greenhouse is not just a box for plants; it is a small climate, a biological instrument, a shelter, a studio, and a conversation between human intention and living systems.

Most domestic growing is still managed by memory, habit, intuition, and occasional panic.

That is not a criticism. Those things matter. Good gardeners notice things.

`jeraenium` starts from the idea that the future of gardening should not replace noticing — it should deepen it.

The project asks:

- What happens if a greenhouse becomes a long-term observational instrument?
- Can sensors support intuition rather than flatten it?
- Can AI help interpret plant and climate signals without becoming intrusive or gimmicky?
- Can small-scale growing become more resilient, beautiful, data-rich, and accessible?
- Can a garden be both a sanctuary and a research platform?
- Can technology make us more attentive to nature, not less?

---

## The short version

`jeraenium` is an evolving blueprint for:

- a sensor-assisted greenhouse
- a garden microclimate observatory
- plant and phenology logging
- DIY automation for irrigation, ventilation, lighting, and environmental alerts
- local-first data collection
- practical guides for low-cost builds
- AI-assisted horticultural reasoning
- video, writing, and storytelling around plant life, systems thinking, and ecological craft
- a future boutique “smart greenhouse” platform

The project is intentionally practical. Each idea should eventually become one of the following:

1. a plant growing better
2. a gardener understanding more
3. a useful dataset
4. a repeatable build
5. a clear guide
6. a beautiful object
7. a less wasteful system
8. a calmer way of living with technology

---

## The name

**jeraenium** is a working project name.

It sits somewhere between:

- *Jeremy*
- *geranium*
- *greenhouse*
- *genus/species language*
- *a personal botanical system*
- *a quiet fictional institute that might become real*

It is deliberately a little strange, but not meaningless.

The name is meant to feel botanical, personal, memorable, and flexible enough to contain gardening, electronics, AI, writing, design, and future products without sounding like a standard tech startup.

---

## Core principles

### 1. Observation before automation

Automation should come after repeated observation.

A watering system should not exist because automation is exciting. It should exist because the plant, substrate, season, and gardener’s routine justify it.

The preferred order is:

```text
observe → record → understand → intervene → automate → review
````

Automation without observation is just remote control with extra steps.

---

### 2. Local-first data

The garden should not need a cloud subscription to remember itself.

Where possible, data should be stored locally, owned by the grower, and available for future tools, dashboards, analysis, or AI models.

A practical version may use:

* ESP32-based sensor nodes
* local Wi-Fi, Ethernet, LoRa, or Bluetooth
* a small local server such as a single-board computer
* SQLite or simple CSV logs
* local APIs
* optional dashboards
* optional AI interpretation
* exportable datasets

The garden’s memory should be portable.

---

### 3. Evidence-informed, not overclaimed

This project is interested in science, but it is not pretending that every home greenhouse is a laboratory.

The goal is to apply good scientific habits at a domestic scale:

* repeated measurements
* clear timestamps
* careful notes
* calibration where possible
* transparent uncertainty
* comparison over time
* avoiding claims beyond the data
* treating sensors as instruments with limitations
* treating plants as living systems, not simple machines

The project values both measured data and human observation.

A leaf curling matters.
A humidity spike matters.
A tomato splitting matters.
A warm night after rain matters.
So does the gardener noticing that “something feels different today.”

---

### 4. Beauty is infrastructure

A system is more likely to survive if it is pleasant to use, look at, repair, and talk about.

This project treats beauty as practical.

Good design helps maintenance.
Good naming helps memory.
Good interfaces help attention.
Good physical layout reduces friction.
Good storytelling keeps the project alive.

The garden is not merely a test bench. It is a place.

---

### 5. Human-scale AI

AI is useful here only if it helps a person grow, notice, decide, learn, and document.

Possible roles for AI:

* summarising greenhouse conditions
* identifying environmental patterns
* comparing current readings with historical baselines
* helping diagnose likely plant stressors
* generating reminders from real observations
* supporting pruning, propagation, and seasonal planning
* turning logs into readable notes
* helping create guides, videos, and documentation
* making the garden more legible without making it less alive

AI should behave more like a careful assistant gardener than a boss.

The working name for the AI layer may become **jeronamo**.

---

## Project architecture

The project can be thought of as several connected layers.

```text
┌──────────────────────────────────────────────┐
│                jeraenium                     │
│  garden + greenhouse + data + craft + AI     │
└──────────────────────────────────────────────┘

        ┌──────────────────────────┐
        │  1. Living systems        │
        │  plants, soil, climate    │
        └────────────┬─────────────┘
                     │
        ┌────────────▼─────────────┐
        │  2. Observation layer     │
        │  notes, photos, phenology │
        └────────────┬─────────────┘
                     │
        ┌────────────▼─────────────┐
        │  3. Sensor layer          │
        │  temp, RH, light, soil    │
        └────────────┬─────────────┘
                     │
        ┌────────────▼─────────────┐
        │  4. Data layer            │
        │  CSV, SQLite, APIs        │
        └────────────┬─────────────┘
                     │
        ┌────────────▼─────────────┐
        │  5. Interpretation layer  │
        │  dashboards, alerts, AI   │
        └────────────┬─────────────┘
                     │
        ┌────────────▼─────────────┐
        │  6. Action layer          │
        │  watering, vents, lights  │
        └────────────┬─────────────┘
                     │
        ┌────────────▼─────────────┐
        │  7. Story layer           │
        │  guides, videos, writing  │
        └──────────────────────────┘
```

---

## The living system

The first and most important layer is the actual garden.

This includes:

* greenhouse crops
* tomatoes
* grape vines
* fruit trees
* grafted apples
* herbs
* ornamentals
* succulents
* climbers
* pollinator plants
* experimental seed-grown plants
* compost
* soil life
* pests and predators
* fungal pressure
* weather exposure
* seasonal change

The living system is not there to serve the technology.

The technology is there to help serve the living system.

---

## The observation layer

Before anything becomes “smart”, it needs memory.

The observation layer records things such as:

* first buds
* first flowers
* first fruit set
* pruning dates
* graft progress
* pest sightings
* disease pressure
* unusual growth
* propagation attempts
* compost starts and finishes
* frost risk
* heat stress
* night humidity
* watering changes
* plant movement
* failures
* surprises

Example observation:

```text
2026-05-18
Greenhouse
Grape vine: vigorous shoot growth; selected potential future canes and tied in.
Tomatoes: continuing training and pruning.
Conditions: warm day, cooler evening.
Note: greenhouse increasingly feels like the central system rather than a side project.
```

These notes matter because plant care is temporal. The value is not only in single events, but in patterns across seasons.

---

## The sensor layer

The current and future sensor layer may include:

| Measurement            | Why it matters                                              |
| ---------------------- | ----------------------------------------------------------- |
| Air temperature        | Growth rate, frost risk, heat stress, germination, ripening |
| Relative humidity      | Fungal risk, transpiration, comfort, ventilation decisions  |
| Dew point              | Condensation risk, leaf wetness, disease pressure           |
| Light level            | Daily light integral proxy, shading, seasonal comparison    |
| Barometric pressure    | Weather change context                                      |
| Soil moisture          | Irrigation timing, dry-down curves                          |
| Soil temperature       | Germination, root activity, seasonal transition             |
| CO₂                    | Ventilation/growth context where measured properly          |
| VOC/eCO₂ trend sensors | Useful as trend indicators, not laboratory truth            |
| Camera snapshots       | Visual record, plant monitoring, AI-assisted comparison     |
| Water flow             | Irrigation confirmation and leak detection                  |
| Tank level             | Water availability and off-grid resilience                  |

A core early system may use:

* ESP32 boards
* temperature/humidity/pressure/light sensors
* local logging
* greenhouse status endpoints
* simple alert logic
* future camera integration
* future plant-level monitoring

---

## Example data model

A simple greenhouse reading might look like:

```csv
timestamp_iso,tC,rH,hPa,lux,dew_point_c
2026-06-03T08:30:00+01:00,18.4,82.1,1008.2,12450,15.2
```

A more developed schema might include:

```text
readings
- id
- timestamp
- node_id
- location
- air_temperature_c
- relative_humidity_pct
- dew_point_c
- pressure_hpa
- lux
- soil_moisture_raw
- soil_temperature_c
- battery_voltage
- signal_strength
- notes
```

Plant observations could be stored separately:

```text
plant_events
- id
- timestamp
- plant_id
- event_type
- description
- image_path
- confidence
- related_reading_id
```

Compost logging could have its own structure:

```text
compost_batches
- id
- bin_id
- start_date
- restart_date
- finish_date
- main_inputs
- moisture_notes
- temperature_notes
- status
```

---

## The data layer

The data layer should be boring, durable, and useful.

Preferred formats:

* CSV for simplicity
* SQLite for structured local storage
* JSON for APIs
* Markdown for human-readable logs
* images stored with timestamps and context

A possible local stack:

```text
ESP32 sensor node
        ↓
local Wi-Fi / Ethernet / LoRa / Bluetooth
        ↓
Khadas VIM4 or similar local server
        ↓
SQLite + CSV exports
        ↓
API endpoints
        ↓
dashboard / phone shortcuts / local AI tools
```

The project should avoid locking its own future behind fragile proprietary systems.

---

## The interpretation layer

Once the greenhouse has memory, it can begin to interpret itself.

Examples:

### Current conditions

```text
Greenhouse: 18.4°C, 82% RH, dew point 15.2°C, bright light.
Ventilation useful soon if humidity rises.
No frost risk.
```

### Pattern detection

```text
Humidity has remained above 95% for 6 hours overnight.
This increases condensation and fungal risk, especially on dense foliage.
Consider morning ventilation and reducing leaf crowding.
```

### Plant-specific notes

```text
Tomatoes are entering a higher-risk period for humidity-related disease.
Prioritise airflow, lower leaf removal where appropriate, and avoid wet foliage overnight.
```

### Seasonal context

```text
The greenhouse is shifting from protection mode into growth management mode.
Main priorities: ventilation, training, watering consistency, and pest observation.
```

The interpretation layer should be humble. It should say “likely”, “possible”, and “worth checking” more often than it says “certain”.

---

## The action layer

Automation should be introduced gradually.

Possible action systems:

| System              | Purpose                                          |
| ------------------- | ------------------------------------------------ |
| Irrigation control  | Reduce drought stress and inconsistent watering  |
| Ventilation control | Reduce overheating and humidity build-up         |
| Fan control         | Improve airflow and reduce fungal pressure       |
| Lighting            | Support propagation or winter growth             |
| Heating             | Frost protection, not energy waste               |
| Shading             | Heat and light moderation                        |
| Alerts              | Help the gardener intervene at the right time    |
| Camera triggers     | Capture change, growth, flowers, pests, failures |

The safest development path:

```text
manual observation
→ sensor visibility
→ alerts
→ assisted decisions
→ semi-automation
→ automation with manual override
```

Manual override is essential.

A living system should not be trapped inside a bad script.

---

## AI layer: jeronamo

The AI part may become its own named layer: **jeronamo**.

Possible meaning:

> **jeronamo**: the interpretive assistant for jeraenium — a local-first AI layer for garden memory, plant reasoning, and greenhouse decision support.

Potential capabilities:

* daily greenhouse briefings
* plant-specific histories
* pest and disease pattern notes
* pruning and training suggestions
* compost progress summaries
* anomaly detection
* seasonal planning
* seed-starting schedules
* local documentation search
* image comparison over time
* “what changed since yesterday?”
* “what should I check today?”
* “what is the most important risk this week?”
* “turn this observation into a useful log entry”

The aim is not to make AI “run the garden”.

The aim is to create a second memory: one that helps the human gardener see the system more clearly.

---

## Possible product architecture

The wider vision could become a set of open, semi-open, and boutique greenhouse tools.

### 1. jeraenium lite

A free, DIY-first version.

For people with:

* a greenhouse
* a few plants
* a phone
* basic tools
* curiosity
* little or no budget

Includes:

* guides
* templates
* low-cost sensor builds
* compost logs
* plant observation logs
* greenhouse setup notes
* seasonal checklists
* simple dashboards
* local-first data principles

### 2. jeraenium frame

A physical greenhouse or retrofit frame concept.

Focus:

* modularity
* repairability
* cable routing
* sensor mounting
* irrigation paths
* ventilation points
* camera positions
* future upgrades

### 3. jeraenium climate kit

A practical environmental monitoring kit.

Possible contents:

* sensor node
* temperature/humidity/pressure/light sensing
* soil moisture option
* basic dashboard
* local logging
* alert rules
* mounting hardware
* documentation

### 4. jeraenium canopy kit

A more complete greenhouse intelligence layer.

Possible contents:

* multiple sensor nodes
* plant zones
* camera support
* irrigation monitoring
* fan/vent/light control
* local server integration
* AI summaries
* data export

### 5. jeraenium prestige kit

A boutique, high-touch system.

Possible contents:

* own-brand sensor housings
* custom dashboard
* greenhouse design consultation
* plant/environment mapping
* training and maintenance guide
* local AI assistant setup
* premium physical finish
* long-term support model

The principle across every tier:

> The free version should still be genuinely useful.

If the low-cost DIY path is not respected, the project loses its soul.

---

## Design language

The visual and physical language should feel:

* botanical
* practical
* calm
* slightly strange
* handmade but competent
* scientific without being sterile
* ecological without being vague
* technological without being soulless

Possible design references:

* field notebooks
* botanical labels
* Victorian glasshouses
* research stations
* weather instruments
* old laboratory equipment
* modern dashboards
* modular synthesizers
* quiet open-source tools
* well-made garden objects

---

## What this is not

`jeraenium` is not trying to be:

* a generic smart home product
* a hype-driven AI startup
* a cloud-only greenhouse subscription
* a replacement for gardening skill
* a fully automated plant factory
* an aesthetic moodboard with no build path
* a pseudo-scientific miracle system
* a productivity cult for plants

The project should remain grounded.

A useful rule:

> If it cannot help a real plant, a real gardener, or a real dataset, it probably does not belong yet.

---

## Current build direction

Near-term practical goals:

* stabilise greenhouse sensor logging
* define clean data formats
* build simple local APIs
* create daily greenhouse summaries
* log plant events consistently
* document composting, pruning, propagation, and seasonal changes
* improve wireless/wired connectivity to garden and greenhouse
* test low-cost irrigation control
* add visual records through camera snapshots
* create simple phone/watch shortcuts for logging and status
* turn repeated work into guides
* publish small, useful artefacts rather than waiting for perfection

---

## Repo structure

Proposed structure:

```text
jeraenium/
├── README.md
├── docs/
│   ├── vision.md
│   ├── principles.md
│   ├── greenhouse-architecture.md
│   ├── data-model.md
│   ├── sensor-notes.md
│   ├── ai-layer-jeronamo.md
│   ├── compost-logging.md
│   ├── plant-logging.md
│   └── product-tiers.md
├── hardware/
│   ├── esp32/
│   ├── sensors/
│   ├── irrigation/
│   ├── power/
│   ├── enclosures/
│   └── mounting/
├── software/
│   ├── firmware/
│   ├── api/
│   ├── database/
│   ├── dashboard/
│   ├── scripts/
│   └── shortcuts/
├── data/
│   ├── samples/
│   ├── schemas/
│   └── exports/
├── garden/
│   ├── plants/
│   ├── observations/
│   ├── phenology/
│   ├── compost/
│   └── experiments/
├── media/
│   ├── photos/
│   ├── diagrams/
│   └── video-notes/
└── prototypes/
    ├── greenhouse-lite/
    ├── climate-kit/
    ├── canopy-kit/
    └── jeronamo/
```

---

## Example greenhouse status API

A simple local endpoint might return:

```json
{
  "timestamp": "2026-06-03T08:30:00+01:00",
  "location": "greenhouse",
  "air_temperature_c": 18.4,
  "relative_humidity_pct": 82.1,
  "dew_point_c": 15.2,
  "pressure_hpa": 1008.2,
  "lux": 12450,
  "status": {
    "frost_risk": false,
    "fungal_risk": "moderate",
    "ventilation_opportunity": true,
    "heat_stress": false
  },
  "summary": "Bright and mild. Humidity is elevated but manageable. Ventilation may be useful later."
}
```

---

## Example daily summary

```text
Greenhouse daily note — 2026-06-03

The greenhouse remained mild overnight with no frost risk.
Humidity rose during the early morning, creating a moderate condensation risk.
Light increased strongly after sunrise.

Suggested checks:
1. Ventilate once outdoor conditions allow.
2. Inspect tomatoes for dense lower foliage.
3. Check grape vine training points.
4. Look for moisture sitting on leaves.
5. Record any new flowers, fruit set, or pest activity.
```

---

## Example plant record

```yaml
plant_id: grapevine_001
common_name: grape vine
location: greenhouse
status: established
training_system: cane/rod development
notes:
  - vigorous seasonal growth
  - selected shoots being tied in for future framework
  - humidity and airflow are important during dense growth
events:
  - date: 2026-05-18
    type: pruning_training
    note: Selected well-positioned shoots for future canes and removed unwanted growth.
```

---

## Example experiment

```markdown
# Experiment: Overnight humidity and tomato disease pressure

## Question

Does overnight relative humidity above 95% correlate with visible fungal pressure on greenhouse tomatoes?

## Method

- Log temperature, relative humidity, and dew point every 5–10 minutes.
- Record hours where RH ≥ 95%.
- Inspect tomato leaves every morning.
- Photograph any visible lesions or mildew.
- Record ventilation actions.
- Compare over several weeks.

## Notes

This is observational, not a controlled trial. Results are useful for this greenhouse first, and more general claims require caution.
```

---

## Evidence-informed anchors

The project draws from several well-established ideas:

* plants respond strongly to microclimate, not just regional weather
* humidity and leaf wetness influence fungal disease risk
* dew point helps estimate condensation risk
* light drives photosynthesis and seasonal growth rhythms
* soil moisture should be interpreted alongside plant stage, substrate, and weather
* repeated observation improves horticultural decision-making
* local datasets become more valuable over time
* automation is safer when it is gradual, observable, and reversible
* AI systems are most useful when grounded in context, history, and uncertainty

The project does not need to overstate these ideas. They are already enough.

---

## Open questions

Good projects leave better questions behind.

Current questions include:

* What is the minimum useful sensor kit for a domestic greenhouse?
* How much can a gardener infer from temperature, humidity, dew point, and light alone?
* Can plant observations and sensor readings be joined into a useful seasonal memory?
* What should AI never be allowed to automate in a garden?
* Can a local AI assistant become a better gardening notebook?
* How can low-cost DIY systems remain beautiful and reliable?
* What does “humane automation” mean in a living system?
* Can greenhouse data help people understand climate, ecology, and care more directly?
* Can a garden become both a refuge and a research instrument?
* What would a genuinely good smart greenhouse feel like to live with?

---

## Roadmap

### Phase 1 — Observe

* [ ] Record greenhouse readings reliably
* [ ] Create plant log templates
* [ ] Create compost log templates
* [ ] Photograph key plants regularly
* [ ] Track pruning, training, flowering, fruiting, pests, and failures
* [ ] Build a simple greenhouse status page or endpoint

### Phase 2 — Understand

* [ ] Add dew point and wetness-risk calculations
* [ ] Summarise daily and weekly patterns
* [ ] Compare sensor data with actual plant events
* [ ] Identify recurring risks: frost, overheating, fungal pressure, drought stress
* [ ] Build simple alerts

### Phase 3 — Assist

* [ ] Create phone/watch shortcuts for logging
* [ ] Generate daily greenhouse briefings
* [ ] Add AI-assisted summaries from local data
* [ ] Build plant-specific histories
* [ ] Create checklists from real observations

### Phase 4 — Act

* [ ] Prototype irrigation control
* [ ] Prototype fan/ventilation control
* [ ] Add manual override
* [ ] Log every automated action
* [ ] Compare plant outcomes before and after automation

### Phase 5 — Share

* [ ] Publish guides
* [ ] Document low-cost builds
* [ ] Create video notes
* [ ] Release templates
* [ ] Share datasets where appropriate
* [ ] Develop `jeraenium lite`

### Phase 6 — Productise carefully

* [ ] Define kit tiers
* [ ] Prototype enclosures
* [ ] Test reliability
* [ ] Improve installation experience
* [ ] Design repairable hardware
* [ ] Keep the free path alive

---

## Invoice footer version

For subtle use at the bottom of invoices:

```text
jeraenium — garden, greenhouse, sensor systems, and humane AI for ecological growing.
https://github.com/YOUR-USERNAME/jeraenium
```

Alternative:

```text
Part of jeraenium: a long-term garden, greenhouse, and local-first AI growing project.
https://github.com/YOUR-USERNAME/jeraenium
```

More mysterious:

```text
Filed under jeraenium — a living greenhouse systems project.
https://github.com/YOUR-USERNAME/jeraenium
```

---

## One-line description

```text
A local-first garden and greenhouse intelligence project combining plants, sensors, ecological observation, DIY automation, and humane AI.
```

---

## Longer description

```text
jeraenium is a practical greenhouse and garden systems project exploring how sensors, local data, plant observation, ecological design, and AI can help people grow with more awareness, resilience, and beauty.
```

---

## Values

* Stay practical.
* Respect the plants.
* Respect the gardener.
* Prefer local ownership.
* Prefer repairable systems.
* Prefer measured claims.
* Prefer beauty with function.
* Prefer guides over gatekeeping.
* Prefer open questions over false certainty.
* Build the smallest useful thing first.
* Let the garden teach the system.

---

## Status

Early, active, living.

This project is being grown in public slowly and practically.
Some parts are working.
Some parts are sketches.
Some parts are experiments.
Some parts are still just good questions.

That is the point.

Gardens are not finished.
Neither is this.

---

## License

To be decided.

Likely direction:

* documentation and guides: Creative Commons style licence
* software: permissive open-source licence
* hardware designs: open hardware licence where appropriate
* product-specific designs: decided later

---

## Closing note

`jeraenium` is a blueprint for a different kind of technological future.

One where intelligence is not only in the machine.
One where the garden is not treated as dumb matter waiting to be controlled.
One where data does not replace attention.
One where automation does not replace care.
One where AI helps a person become more present, not less.

A greenhouse can be a place to grow food.
It can be a place to grow plants.
It can also be a place to grow perception.

That is the work.