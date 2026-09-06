import React from 'react';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import styles from './index.module.css';

function SpecCard({ title, description, to }) {
  return (
    <div className={styles.specCard}>
      <h3>{title}</h3>
      <p>{description}</p>
      <Link to={to} className="button button--primary button--sm">
        Read →
      </Link>
    </div>
  );
}

export default function Home() {
  const { siteConfig } = useDocusaurusContext();
  return (
    <Layout title={siteConfig.title} description={siteConfig.tagline}>
      <header className="hero hero--primary">
        <div className="container">
          <h1 className="hero__title">TURTLE<br />READER</h1>
          <p className="hero__subtitle">
            Fantasy console · ESP32-S3 · Lua 5.4 · 164×124 px · 32 colors
          </p>
          <div className={styles.heroCta}>
            <Link className="button button--primary button--lg" to="/intro">
              Get Started
            </Link>
            <Link className="button button--secondary button--lg" to="/lua/overview">
              Lua API
            </Link>
          </div>
        </div>
      </header>

      <main className={styles.main}>
        <div className="container">
          <div className={styles.specs}>
            <div className={styles.specBadge}>
              <span>164×124</span><label>Resolution</label>
            </div>
            <div className={styles.specBadge}>
              <span>32</span><label>Colors</label>
            </div>
            <div className={styles.specBadge}>
              <span>Lua 5.4</span><label>Scripting</label>
            </div>
            <div className={styles.specBadge}>
              <span>ESP32-S3</span><label>Hardware</label>
            </div>
            <div className={styles.specBadge}>
              <span>microSD</span><label>Cartridges</label>
            </div>
          </div>

          <section className={styles.cardGrid}>
            <SpecCard
              title=".turtlecart"
              description="Plain-text cartridge format. Entry Lua, palette, embedded files, and scene boot."
              to="/cartridge/turtlecart-format"
            />
            <SpecCard
              title="Lua API"
              description="Two VM model: ENTRY for boot, actor scripts for per-frame game logic."
              to="/lua/overview"
            />
            <SpecCard
              title="Asset Formats"
              description="Binary codecs for sprites (.tsp), backgrounds (.tbg), tilesets (.tts), and fonts (.tfn)."
              to="/assets/binary-formats"
            />
            <SpecCard
              title="TurtleStudio"
              description="Python authoring tool with Dear PyGui GUI for building and exporting .tortucart projects."
              to="/turtlestudio/guide"
            />
          </section>
        </div>
      </main>
    </Layout>
  );
}
