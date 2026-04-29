# Apache Iceberg Expert Roadmap - Quick Reference

## 📁 Files Created

### 1. **Apache_Iceberg_Learning_Roadmap.md**
**Type:** Comprehensive Word Document (Markdown → Docx)
**Pages:** ~60 pages
**Purpose:** Complete learning guide with detailed content for all 8 weeks

**Contents:**
- Executive Summary
- Week-by-week breakdown (1-2: Beginner, 3-4: Intermediate, 5-7: Advanced, 8: Expert)
- Detailed learning objectives per week
- Hands-on lab instructions
- Resources and references
- Assessment criteria
- Glossary and FAQ

**How to Use:**
1. Convert to Word: `pandoc Apache_Iceberg_Learning_Roadmap.md -o Apache_Iceberg_Learning_Roadmap.docx`
2. Or open in any Markdown editor for reading
3. Print or share as PDF for offline reference

---

### 2. **Apache_Iceberg_Roadmap_Slides_Content.md**
**Type:** Google Slides Content (58 slides)
**Purpose:** Presentation deck for stakeholder enablement

**Contents:**
- Title and agenda slides
- Section breakers for each week
- Visual comparisons (Iceberg vs Delta vs Hudi)
- Architecture diagrams (text descriptions)
- Milestone checklists
- Final expert challenge
- Resources and Q&A

**How to Use:**
1. Open Confluent Template: https://docs.google.com/presentation/d/1VEakn4Dk9MnpvI2fxs9lBwkxnuJukZA54iSLOPROHhs
2. File → Make a Copy
3. Copy content from this file to corresponding slides
4. Use template layouts as specified
5. Add visuals using template icon library

---

## 🎯 Quick Start Guide

### For Self-Learning:
1. **Read:** Apache_Iceberg_Learning_Roadmap.md
2. **Follow:** Week-by-week schedule
3. **Practice:** Complete all 15+ hands-on labs
4. **Certify:** Pass final expert challenge

### For Presentations:
1. **Create:** Google Slides from template
2. **Populate:** Copy content from Slides_Content.md
3. **Customize:** Add customer-specific examples
4. **Present:** To technical and business stakeholders

### For Team Enablement:
1. **Share:** Both documents with team
2. **Schedule:** Weekly learning sessions
3. **Track:** Progress using milestone checklists
4. **Support:** Set up Slack channel for questions

---

## 📊 Document Structure Comparison

| Feature | Word Document | Slides Deck |
|---------|--------------|-------------|
| **Depth** | Very detailed | High-level |
| **Use Case** | Self-study, reference | Presentations |
| **Format** | Narrative, step-by-step | Visual, bullet points |
| **Labs** | Detailed instructions | Summary only |
| **Duration** | 8 weeks of material | 45-60 min presentation |
| **Audience** | Individual learners | Groups, stakeholders |

---

## 🛠️ Converting Markdown to Other Formats

### To Word (Docx):
```bash
# Using Pandoc
pandoc Apache_Iceberg_Learning_Roadmap.md -o Apache_Iceberg_Learning_Roadmap.docx

# With table of contents
pandoc Apache_Iceberg_Learning_Roadmap.md --toc -o Apache_Iceberg_Learning_Roadmap.docx
```

### To PDF:
```bash
# Using Pandoc
pandoc Apache_Iceberg_Learning_Roadmap.md -o Apache_Iceberg_Learning_Roadmap.pdf

# With better formatting
pandoc Apache_Iceberg_Learning_Roadmap.md --toc --pdf-engine=xelatex -o Apache_Iceberg_Learning_Roadmap.pdf
```

### To HTML:
```bash
pandoc Apache_Iceberg_Learning_Roadmap.md -o Apache_Iceberg_Learning_Roadmap.html
```

---

## 🎨 Confluent Template Reference

**Template URL:** https://docs.google.com/presentation/d/1VEakn4Dk9MnpvI2fxs9lBwkxnuJukZA54iSLOPROHhs

**Key Design Elements:**
- **Font:** Inter (switched from Montserrat in August 2024)
- **Primary Colors:**
  - Midnight: #040531
  - Ocean: #0099FF
  - Mist: #F5F7FF
  - Snow: #FBFBFB
  - White: #FFFFFF
- **Secondary Colors:**
  - Grape: #AA2BCE
  - Han: #3A21ED
  - Yale: #14449A
  - Steel: #0074A2
  - Marlin: #01CEDB
  - Punch: #D8365D

**Layout Types:**
- Title Slides (with/without speaker photo)
- Agenda Slides (5-item, 10-item)
- Section Breakers (dark background)
- Content Layouts (split view, boxes, icons)
- Comparison Tables
- Architecture Diagrams

---

## 📚 Key Resources Referenced

### Official Documentation:
- [Apache Iceberg Docs](https://iceberg.apache.org/)
- [Confluent Tableflow Docs](https://docs.confluent.io/cloud/current/tableflow/)
- [Confluent Developer](https://developer.confluent.io/courses/)

### Internal Resources:
- [Tableflow Main Deck v1.2](https://docs.google.com/presentation/d/189kHEEAjgW6VRkTOaJZEA9pW-JHzG8rFSjGItvn416Q)
- [Tableflow L200 Content](https://docs.google.com/presentation/d/11e6L7gav0-h9MqBzYLrFeKCZzLmB-gCUTZ_W-GLV9Jw)
- [Tableflow Product Overview](https://docs.google.com/presentation/d/1Li8lylvPf9jVos74GESSN-GNMp6k-JmQQDn7oQeNh20)
- [Iceberg + Tableflow Course](https://confluentinc.atlassian.net/wiki/spaces/DEVX/pages/4281860372)

### Blogs:
- [Introducing Tableflow](https://www.confluent.io/blog/introducing-tableflow/)
- [Tableflow GA: Kafka to Iceberg](https://www.confluent.io/blog/tableflow-ga-kafka-snowflake-iceberg/)
- [Tableflow is Generally Available](https://www.confluent.io/blog/tableflow-is-now-generally-available/)

---

## ✅ Checklist for Using These Documents

### Before Starting:
- [ ] Install Pandoc (for document conversion)
- [ ] Access Confluent Cloud account
- [ ] Bookmark all resource links
- [ ] Set up Confluent template access
- [ ] Join #tableflow and #iceberg Slack channels

### Week 1-2 (Beginner):
- [ ] Read Word doc sections for Week 1-2
- [ ] Watch Apache Iceberg 101 course
- [ ] Complete beginner quiz
- [ ] Create comparison table

### Week 3-4 (Intermediate):
- [ ] Complete all 5 hands-on labs
- [ ] Draw architecture from memory
- [ ] Pass intermediate quiz
- [ ] Set up test environment

### Week 5-7 (Advanced):
- [ ] Practice schema evolution
- [ ] Optimize query performance
- [ ] Integrate 3+ query engines
- [ ] Build monitoring dashboard

### Week 8 (Expert):
- [ ] Design production architecture
- [ ] Complete final expert challenge
- [ ] Create presentation from slides
- [ ] Present to stakeholders

### After Certification:
- [ ] Share knowledge with team
- [ ] Contribute to community
- [ ] Mentor junior engineers
- [ ] Stay updated with releases

---

## 🎓 Learning Path Summary

```
START HERE
    ↓
Week 1-2: Read "Why Iceberg?"
    ↓
Week 3-4: Build hands-on skills
    ↓
Week 5-7: Master advanced features
    ↓
Week 8: Production deployment
    ↓
EXPERT CERTIFIED
    ↓
Continuous Learning
```

---

## 💡 Tips for Success

1. **Daily Commitment:** Block 2-3 hours daily for focused learning
2. **Hands-On First:** Do labs immediately after reading concepts
3. **Real Projects:** Apply learning to actual customer scenarios
4. **Community:** Ask questions in Slack, don't struggle alone
5. **Document:** Keep notes of challenges and solutions
6. **Practice:** Repetition builds expertise
7. **Teach:** Explaining to others solidifies your knowledge

---

## 📞 Support

**Questions about the roadmap?**
- Internal: #csta-enablement Slack channel
- Tableflow: #tableflow Slack channel
- Iceberg: #iceberg Slack channel

**Resources:**
- [CSTA Technical Enablement Decks](https://confluentinc.atlassian.net/wiki/display/CSE/Customer+Technical+Enablement+Decks)
- [Customer Technical Enablement Guide](https://confluentinc.atlassian.net/wiki/display/CSE/Customer+Technical+Enablement+-+Development+Guide)

---

## 📅 Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | March 12, 2026 | Initial release |

---

**Happy Learning! 🚀**

Transform from beginner to Apache Iceberg expert in 8 weeks.
