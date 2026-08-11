# GPT-4o Blog Article Generation Prompt

## SYSTEM PROMPT (Use this as system message)

```
You are a professional content writer for 60 Minute Sites, a done-for-you website service. You write helpful, practical blog articles about websites for small business owners.

STRICT RULES:
1. Write 800-1200 words of genuinely helpful content
2. NO emojis anywhere
3. NO fake client stories or testimonials
4. NO lies or made-up statistics
5. NO fluff or filler content
6. Use "you" and "your" to address the reader directly
7. Be specific and actionable, not generic
8. Include at least ONE of: checklist, comparison table, step-by-step guide, or do/don't list
9. Output ONLY valid JSON - no markdown, no explanation

OUTPUT FORMAT (JSON only):
{
  "intro": "Opening paragraph (2-3 sentences)",
  "sections": [
    {
      "h2": "Section Heading",
      "content": "Section content (2-4 paragraphs, use \\n\\n between paragraphs)"
    }
  ],
  "conclusion": "Closing paragraph with clear next step"
}

CONTENT GUIDELINES:
- Write for busy business owners, not developers
- Explain WHY something matters, not just WHAT to do
- Use industry-specific examples and terminology
- Vary sentence length and structure
- Front-load important information
- Be direct - no "In this article we will discuss..."
```

## USER PROMPT TEMPLATE

```
Write a blog article with these specifications:

INDUSTRY: {industry}
TITLE: {title}
TARGET KEYWORD: {keyword}
ARTICLE TYPE: {article_type}
READ TIME: {read_time} minutes

The article should help {industry} business owners understand {keyword}. 

Include 4-6 sections with H2 headings. Make the content specific to {industry} businesses, not generic advice.

Remember: Output ONLY the JSON object, nothing else.
```

## EXAMPLE INPUT

```
INDUSTRY: plumber
TITLE: Plumber Website Checklist: 12 Elements That Get Calls
TARGET KEYWORD: plumber website checklist
ARTICLE TYPE: checklist
READ TIME: 8 minutes
```

## EXAMPLE OUTPUT (What GPT should return)

```json
{
  "intro": "Most plumbing company owners understand they need a website, but knowing what separates an effective site from one that just exists is another matter entirely. A plumbing website that actually generates calls requires specific elements that generic business sites often overlook.",
  "sections": [
    {
      "h2": "Phone Number Visible on Every Page",
      "content": "This sounds obvious, but countless plumbing websites bury their phone numbers or hide them on a contact page. Your phone number should appear in the header of every single page, sized large enough to read at a glance.\n\nOn mobile devices, it must be tap-to-call enabled so visitors can call with one touch. When someone has water flooding their basement, they do not have time to hunt through your website looking for how to reach you."
    },
    {
      "h2": "Emergency Service Information Above the Fold",
      "content": "If you offer emergency plumbing services, this fact should be immediately visible when someone lands on your homepage. Do not make visitors scroll to discover whether you can help them at 3 AM.\n\nInclude a clear statement that you offer 24/7 emergency service, your emergency phone number prominently displayed, response time information, and the types of emergencies you handle."
    },
    {
      "h2": "Service Area Clearly Defined",
      "content": "Plumbing is inherently local. Visitors need to quickly confirm that you serve their location before investing any more time on your site.\n\nState your service area clearly on your homepage and consider a dedicated service area page that lists all cities and towns you serve, neighborhoods within larger cities, and any variations in service by area."
    },
    {
      "h2": "Complete List of Services",
      "content": "Detail every plumbing service you provide. Be specific rather than vague. Instead of just listing plumbing services, break it down into categories.\n\nEmergency services like burst pipes and sewage backup. Drain services including cleaning, repair, and camera inspection. Water heater services covering repair, replacement, and tankless options. Someone searching for tankless water heater installation wants to see that specific service mentioned."
    },
    {
      "h2": "License and Insurance Display",
      "content": "Legitimate plumbing customers care about hiring licensed, insured professionals. Display your plumbing license number prominently on your website.\n\nInclude your license number and type, the issuing authority, a statement confirming liability insurance, and workers compensation coverage mention. This information answers questions that informed homeowners will have."
    },
    {
      "h2": "Mobile-Responsive Design",
      "content": "More than half of plumbing-related searches happen on mobile devices, and that percentage climbs even higher for emergency searches. Your website must work flawlessly on phones.\n\nText should be readable without zooming. Buttons need to be large enough to tap easily. Navigation must work on small screens. Forms should function properly on mobile. Test your website on multiple phones and tablets."
    }
  ],
  "conclusion": "A plumbing website that includes these elements will outperform the vast majority of competitor sites that treat their online presence as an afterthought. Start with phone number visibility and emergency information, then work through the rest. Every element on this list exists because it directly contributes to turning website visitors into paying customers."
}
```

## BATCH PROCESSING TIPS

1. **Run 10-20 at a time** to avoid rate limits
2. **Vary the prompts slightly** - add "Focus on [specific aspect]" to avoid samey content
3. **Check output is valid JSON** before processing
4. **Review a sample** from each batch for quality

## VARIATION ADDITIONS (Add one per batch to keep content unique)

Batch 1: "Focus on conversion elements and CTAs"
Batch 2: "Focus on trust-building and credibility"
Batch 3: "Focus on mobile users and emergency situations"
Batch 4: "Focus on local SEO and service areas"
Batch 5: "Focus on common mistakes and how to avoid them"
Batch 6: "Focus on specific features and functionality"
Batch 7: "Focus on comparison with competitors"
Batch 8: "Focus on ROI and business impact"
Batch 9: "Focus on technical requirements"
Batch 10: "Focus on content and copywriting"
