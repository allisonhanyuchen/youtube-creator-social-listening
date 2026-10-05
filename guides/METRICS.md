# Metrics, data and privacy

## Definitions

- **Lift**: a video's views divided by the median views of the same channel's comparable pre-launch videos (Shorts with Shorts, long with long), then divided by the typical value among videos of the same product and format. 1.0 is a typical video.
- **Outperformer**: top quarter of lift within its format class. **Underperformer**: bottom quarter.
- **Sentiment score**: positive share minus negative share of the comments about the product, price, Apple or competitors (comments about the video or creator are left out). A video needs at least 10 such comments before its reaction is shown.
- **Views gained (24h / 7d)**: views added since the latest daily snapshot that is at least a day (or a week) old. The API has no history, so `snapshots.py` stores one count a day; the columns fill in as snapshots accumulate.
- **Topic trend**: the share of a topic's comments posted in the last 7 days divided by its usual share. Above 1.5x with 15+ recent comments is "gaining". New topics are marked "new this week".
- **Channel size**: small (under 250k subscribers), mid (250k to 1M), large (1M and above).


## Data and limits

- English-language videos found through search: a sample of YouTube, not a census. Comments are up to 60 per video (40 top, 20 newest), so liked opinions are over-represented. Labels come from Claude and were produced in two modes (deeper reasoning, then a faster one).
- About 85% of product comments fit a topic; the rest are shown as unassigned. In the scheduled run old comment text is not kept, so new topics are discovered among that run's unassigned comments.
- Region is the channel-declared country. Lift compares a video with its own channel, so small channels reach high multiples more easily; differences between groups are associations.
- Sponsorship and Apple seeding are deliberately not analysed: in an earlier version none of the 58 sponsored videos was sponsored by Apple or a competitor, and seeding could only be inferred from timing, which also drives views.


## Privacy and keys

Comment text, the SQLite database and the local dashboard (which embeds a few hundred quotes) stay on your machine and are git-ignored. The public page contains no comment text; its paraphrased notes and recorded answers are checked at build time and the build fails if any shares a distinctive 5-word run with a comment. Only code and text-free state are committed: video titles, IDs and public stats, our labels per comment ID, baselines, topics and snapshots. API keys are never stored in the repository, and the demo code lives only in the host's environment.
